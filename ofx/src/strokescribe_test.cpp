// StrokeScribe Test — a minimal OpenFX effect for trying StrokeScribe inside Filmora.
//
// What it does: on any clip, a hand draws a line along a path over "Draw time"
// seconds, on top of the clip's picture. What it is for: finding out how the
// host behaves (clip time, frame rate, image formats, render scale) before the
// real StrokeScribe effect is built. Every render writes a short line to
//   %LOCALAPPDATA%\StrokeScribe\ofx-test.log
//
// Crash safety: nothing throws across the plugin boundary; every image format
// OFX allows (8-bit, 16-bit, float; RGBA, RGB, Alpha) is handled; any failure
// while drawing falls back to copying the clip unchanged.
//
// OpenFX C API only (BSD-licensed headers). stb_image (public domain) decodes
// the built-in hand picture embedded at build time.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <string>
#include <vector>

#include "ofxCore.h"
#include "ofxImageEffect.h"
#include "ofxParam.h"
#include "ofxProperty.h"

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#include "stb_image.h"

#include "hand_png.h"   // const unsigned char kHandPng[]; const unsigned int kHandPngSize;

#ifdef _WIN32
#include <direct.h>
#define SS_MKDIR(p) _mkdir(p)
#else
#include <sys/stat.h>
#define SS_MKDIR(p) mkdir(p, 0755)
#endif

static const char *kPluginId = "com.strokedot.strokescribe.test";
static const char *kVersionLabel = "0.1.0";

static OfxHost *gHost = nullptr;
static const OfxPropertySuiteV1 *gProp = nullptr;
static const OfxImageEffectSuiteV1 *gEffect = nullptr;
static const OfxParameterSuiteV1 *gParam = nullptr;

// ------------------------------------------------------------------ logging
static std::mutex gLogMutex;
static std::atomic<long> gRenderCount{0};

static std::string logPath() {
    const char *base = std::getenv("LOCALAPPDATA");
    std::string dir = base ? std::string(base) : std::string(".");
#ifdef _WIN32
    dir += "\\StrokeScribe";
    SS_MKDIR(dir.c_str());
    return dir + "\\ofx-test.log";
#else
    dir += "/StrokeScribe";
    SS_MKDIR(dir.c_str());
    return dir + "/ofx-test.log";
#endif
}

static void logLine(const char *format, ...) {
    try {
        std::lock_guard<std::mutex> lock(gLogMutex);
        FILE *f = std::fopen(logPath().c_str(), "a");
        if (!f) return;
        std::time_t now = std::time(nullptr);
        char stamp[32] = {0};
        std::strftime(stamp, sizeof(stamp), "%Y-%m-%d %H:%M:%S", std::localtime(&now));
        std::fprintf(f, "%s  ", stamp);
        va_list args;
        va_start(args, format);
        std::vfprintf(f, format, args);
        va_end(args);
        std::fputc('\n', f);
        std::fclose(f);
    } catch (...) {
    }
}

// ------------------------------------------------------------------ the hand
struct HandImage {
    int w = 0, h = 0;
    std::vector<float> rgba;   // straight alpha, 0..1, top row first
    bool ok = false;
};
static HandImage gHand;
static std::once_flag gHandOnce;

static void loadHand() {
    int w = 0, h = 0, n = 0;
    unsigned char *data = stbi_load_from_memory(kHandPng, (int)kHandPngSize, &w, &h, &n, 4);
    if (!data) { logLine("hand image could not be decoded"); return; }
    gHand.w = w; gHand.h = h;
    gHand.rgba.resize((size_t)w * h * 4);
    for (size_t i = 0; i < gHand.rgba.size(); ++i) gHand.rgba[i] = data[i] / 255.f;
    stbi_image_free(data);
    gHand.ok = true;
}

// Pen tip of the built-in StrokeScribe hand (fractions of the picture, top-left origin).
static const float kTipX = 0.08f, kTipY = 0.13f;

// ------------------------------------------------------------------ helpers
static double getDouble(OfxPropertySetHandle p, const char *name, int i, double fallback) {
    double v = fallback;
    if (!p || gProp->propGetDouble(p, name, i, &v) != kOfxStatOK) return fallback;
    return v;
}
static int getInt(OfxPropertySetHandle p, const char *name, int i, int fallback) {
    int v = fallback;
    if (!p || gProp->propGetInt(p, name, i, &v) != kOfxStatOK) return fallback;
    return v;
}
static std::string getString(OfxPropertySetHandle p, const char *name, int i, const char *fallback) {
    char *v = nullptr;
    if (!p || gProp->propGetString(p, name, i, &v) != kOfxStatOK || !v) return fallback;
    return v;
}

struct Params {
    double drawSeconds = 4, lineWidth = 6, handSize = .45;
    double r = .15, g = .21, b = .29;
    int showHand = 1, shape = 0, log = 1;
};

static Params readParams(OfxImageEffectHandle effect, OfxTime time) {
    Params out;
    OfxParamSetHandle set = nullptr;
    if (gEffect->getParamSet(effect, &set) != kOfxStatOK) return out;
    OfxParamHandle h = nullptr;
    if (gParam->paramGetHandle(set, "drawTime", &h, nullptr) == kOfxStatOK) gParam->paramGetValueAtTime(h, time, &out.drawSeconds);
    if (gParam->paramGetHandle(set, "lineWidth", &h, nullptr) == kOfxStatOK) gParam->paramGetValueAtTime(h, time, &out.lineWidth);
    if (gParam->paramGetHandle(set, "handSize", &h, nullptr) == kOfxStatOK) gParam->paramGetValueAtTime(h, time, &out.handSize);
    if (gParam->paramGetHandle(set, "inkColour", &h, nullptr) == kOfxStatOK) gParam->paramGetValueAtTime(h, time, &out.r, &out.g, &out.b);
    if (gParam->paramGetHandle(set, "showHand", &h, nullptr) == kOfxStatOK) gParam->paramGetValueAtTime(h, time, &out.showHand);
    if (gParam->paramGetHandle(set, "shape", &h, nullptr) == kOfxStatOK) gParam->paramGetValueAtTime(h, time, &out.shape);
    if (gParam->paramGetHandle(set, "writeLog", &h, nullptr) == kOfxStatOK) gParam->paramGetValueAtTime(h, time, &out.log);
    out.drawSeconds = std::max(0.2, out.drawSeconds);
    return out;
}

// ------------------------------------------------------------------ images
// A float RGBA working canvas, top row first (OFX images are bottom row first).
struct Canvas {
    int w = 0, h = 0;
    std::vector<float> px;   // premultiplied RGBA
    float *at(int x, int y) { return &px[((size_t)y * w + x) * 4]; }
};

struct OfxImage {
    void *data = nullptr;
    int x1 = 0, y1 = 0, x2 = 0, y2 = 0, rowBytes = 0, comps = 4, depth = 1;  // depth: bytes per channel (4 = float)
    bool ok = false;
};

static OfxImage describeImage(OfxPropertySetHandle img) {
    OfxImage out;
    if (!img) return out;
    gProp->propGetPointer(img, kOfxImagePropData, 0, &out.data);
    int b[4] = {0, 0, 0, 0};
    gProp->propGetIntN(img, kOfxImagePropBounds, 4, b);
    out.x1 = b[0]; out.y1 = b[1]; out.x2 = b[2]; out.y2 = b[3];
    out.rowBytes = getInt(img, kOfxImagePropRowBytes, 0, 0);
    std::string comps = getString(img, kOfxImageEffectPropComponents, 0, kOfxImageComponentRGBA);
    out.comps = comps == kOfxImageComponentRGBA ? 4 : comps == kOfxImageComponentRGB ? 3 : comps == kOfxImageComponentAlpha ? 1 : 0;
    std::string depth = getString(img, kOfxImageEffectPropPixelDepth, 0, kOfxBitDepthByte);
    out.depth = depth == kOfxBitDepthFloat ? 4 : depth == kOfxBitDepthShort ? 2 : depth == kOfxBitDepthByte ? 1 : 0;
    out.ok = out.data && out.comps && out.depth && out.x2 > out.x1 && out.y2 > out.y1;
    return out;
}

static inline unsigned char *pixelAddr(const OfxImage &im, int x, int y) {
    return (unsigned char *)im.data + (ptrdiff_t)(y - im.y1) * im.rowBytes + (ptrdiff_t)(x - im.x1) * im.comps * im.depth;
}

static inline float readChannel(const unsigned char *p, int depth) {
    if (depth == 1) return *p / 255.f;
    if (depth == 2) return *(const unsigned short *)p / 65535.f;
    return *(const float *)p;
}
static inline void writeChannel(unsigned char *p, int depth, float v) {
    if (depth == 4) { *(float *)p = v; return; }
    v = std::min(1.f, std::max(0.f, v));
    if (depth == 1) *p = (unsigned char)std::lround(v * 255.f);
    else *(unsigned short *)p = (unsigned short)std::lround(v * 65535.f);
}

// Copy the window of `src` (may be missing) into a canvas of the window's size.
static void readInto(Canvas &c, const OfxImage &src, int wx1, int wy1, int wx2, int wy2) {
    c.w = wx2 - wx1; c.h = wy2 - wy1;
    c.px.assign((size_t)c.w * c.h * 4, 0.f);
    if (!src.ok) return;
    for (int y = wy1; y < wy2; ++y) {
        if (y < src.y1 || y >= src.y2) continue;
        int row = (wy2 - 1 - y);   // top row first
        for (int x = wx1; x < wx2; ++x) {
            if (x < src.x1 || x >= src.x2) continue;
            const unsigned char *p = pixelAddr(src, x, y);
            float *d = c.at(x - wx1, row);
            if (src.comps == 1) { float a = readChannel(p, src.depth); d[0] = d[1] = d[2] = 0; d[3] = a; continue; }
            for (int k = 0; k < 3; ++k) d[k] = readChannel(p + k * src.depth, src.depth);
            d[3] = src.comps == 4 ? readChannel(p + 3 * src.depth, src.depth) : 1.f;
        }
    }
}

static void writeFrom(const Canvas &c, const OfxImage &dst, int wx1, int wy1, int wx2, int wy2) {
    for (int y = std::max(wy1, dst.y1); y < std::min(wy2, dst.y2); ++y) {
        int row = (wy2 - 1 - y);
        for (int x = std::max(wx1, dst.x1); x < std::min(wx2, dst.x2); ++x) {
            const float *s = &c.px[((size_t)row * c.w + (x - wx1)) * 4];
            unsigned char *p = pixelAddr(dst, x, y);
            if (dst.comps == 1) { writeChannel(p, dst.depth, s[3]); continue; }
            for (int k = 0; k < 3; ++k) writeChannel(p + k * dst.depth, dst.depth, s[k]);
            if (dst.comps == 4) writeChannel(p + 3 * dst.depth, dst.depth, s[3]);
        }
    }
}

// Source-over of a premultiplied colour with coverage `a` onto the canvas.
static inline void blend(float *d, float r, float g, float b, float a) {
    if (a <= 0) return;
    a = std::min(1.f, a);
    d[0] = r * a + d[0] * (1 - a);
    d[1] = g * a + d[1] * (1 - a);
    d[2] = b * a + d[2] * (1 - a);
    d[3] = a + d[3] * (1 - a);
}

// ------------------------------------------------------------------ the path
// Points in 0..1 frame coordinates (top-left origin).
static std::vector<std::pair<float, float>> pathFor(int shape) {
    std::vector<std::pair<float, float>> pts;
    const float pi = 3.14159265f;
    if (shape == 1) {                       // spiral
        for (int i = 0; i <= 600; ++i) {
            float t = i / 600.f, a = t * 6 * pi, r = .05f + .32f * t;
            pts.push_back({.5f + r * std::cos(a) * .56f, .5f + r * std::sin(a)});
        }
    } else if (shape == 2) {                // star
        for (int i = 0; i <= 10; ++i) {
            float a = -pi / 2 + i * 4 * pi / 5;
            pts.push_back({.5f + .22f * std::cos(a), .5f + .38f * std::sin(a)});
        }
    } else {                                // a handwriting-like wave
        for (int i = 0; i <= 800; ++i) {
            float t = i / 800.f, x = .12f + .76f * t;
            float y = .5f + .12f * std::sin(t * 9 * pi) * std::sin(t * pi) + .04f * std::sin(t * 31 * pi);
            pts.push_back({x, y});
        }
    }
    return pts;
}

static void drawStroke(Canvas &c, const Params &p, double progress, float scale, float &tipX, float &tipY) {
    auto pts = pathFor(p.shape);
    std::vector<float> len(pts.size(), 0.f);
    for (size_t i = 1; i < pts.size(); ++i) {
        float dx = (pts[i].first - pts[i - 1].first) * c.w, dy = (pts[i].second - pts[i - 1].second) * c.h;
        len[i] = len[i - 1] + std::sqrt(dx * dx + dy * dy);
    }
    float goal = (float)(std::min(1.0, std::max(0.0, progress)) * len.back());
    float radius = std::max(.6f, (float)p.lineWidth * scale * .5f);
    float r = (float)p.r, g = (float)p.g, b = (float)p.b;
    tipX = pts[0].first * c.w; tipY = pts[0].second * c.h;
    if (goal <= 0) return;
    // Stamp discs along the path every half radius (anti-aliased edge).
    float step = std::max(.5f, radius * .5f);
    std::vector<float> cover((size_t)c.w * c.h, 0.f);
    for (size_t i = 1; i < pts.size() && len[i - 1] < goal; ++i) {
        float x0 = pts[i - 1].first * c.w, y0 = pts[i - 1].second * c.h;
        float x1 = pts[i].first * c.w, y1 = pts[i].second * c.h;
        float seg = len[i] - len[i - 1];
        float until = std::min(goal, len[i]) - len[i - 1];
        for (float d = 0; d <= until; d += step) {
            float f = seg > 0 ? d / seg : 0;
            float cx = x0 + (x1 - x0) * f, cy = y0 + (y1 - y0) * f;
            tipX = cx; tipY = cy;
            int ax = (int)std::floor(cx - radius - 1), bx = (int)std::ceil(cx + radius + 1);
            int ay = (int)std::floor(cy - radius - 1), by = (int)std::ceil(cy + radius + 1);
            for (int y = std::max(0, ay); y < std::min(c.h, by); ++y)
                for (int x = std::max(0, ax); x < std::min(c.w, bx); ++x) {
                    float dist = std::sqrt((x + .5f - cx) * (x + .5f - cx) + (y + .5f - cy) * (y + .5f - cy));
                    float a = std::min(1.f, std::max(0.f, radius + .5f - dist));
                    float &cv = cover[(size_t)y * c.w + x];
                    cv = std::max(cv, a);
                }
        }
    }
    for (int y = 0; y < c.h; ++y)
        for (int x = 0; x < c.w; ++x) {
            float a = cover[(size_t)y * c.w + x];
            if (a > 0) blend(c.at(x, y), r, g, b, a);
        }
}

static void drawHand(Canvas &c, const Params &p, float tipX, float tipY) {
    std::call_once(gHandOnce, loadHand);
    if (!gHand.ok || !p.showHand) return;
    float height = (float)p.handSize * c.h;
    float s = height / gHand.h;                     // canvas pixels per hand pixel
    float width = gHand.w * s;
    float left = tipX - kTipX * width, top = tipY - kTipY * height;
    int ax = std::max(0, (int)std::floor(left)), bx = std::min(c.w, (int)std::ceil(left + width));
    int ay = std::max(0, (int)std::floor(top)), by = std::min(c.h, (int)std::ceil(top + height));
    for (int y = ay; y < by; ++y)
        for (int x = ax; x < bx; ++x) {
            // Bilinear sample of the hand picture.
            float u = (x + .5f - left) / s - .5f, v = (y + .5f - top) / s - .5f;
            int u0 = (int)std::floor(u), v0 = (int)std::floor(v);
            float fu = u - u0, fv = v - v0;
            float acc[4] = {0, 0, 0, 0};
            for (int j = 0; j < 2; ++j)
                for (int i = 0; i < 2; ++i) {
                    int uu = std::min(gHand.w - 1, std::max(0, u0 + i)), vv = std::min(gHand.h - 1, std::max(0, v0 + j));
                    float wgt = (i ? fu : 1 - fu) * (j ? fv : 1 - fv);
                    const float *q = &gHand.rgba[((size_t)vv * gHand.w + uu) * 4];
                    acc[0] += q[0] * q[3] * wgt; acc[1] += q[1] * q[3] * wgt; acc[2] += q[2] * q[3] * wgt; acc[3] += q[3] * wgt;
                }
            if (acc[3] <= 0) continue;
            float *d = c.at(x, y);
            float a = std::min(1.f, acc[3]);
            d[0] = acc[0] + d[0] * (1 - a);
            d[1] = acc[1] + d[1] * (1 - a);
            d[2] = acc[2] + d[2] * (1 - a);
            d[3] = a + d[3] * (1 - a);
        }
}

// ------------------------------------------------------------------ actions
static OfxStatus onLoad() {
    if (!gHost) return kOfxStatErrMissingHostFeature;
    gProp = (const OfxPropertySuiteV1 *)gHost->fetchSuite(gHost->host, kOfxPropertySuite, 1);
    gEffect = (const OfxImageEffectSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxImageEffectSuite, 1);
    gParam = (const OfxParameterSuiteV1 *)gHost->fetchSuite(gHost->host, kOfxParameterSuite, 1);
    if (!gProp || !gEffect || !gParam) return kOfxStatErrMissingHostFeature;
    logLine("loaded StrokeScribe Test %s in host '%s' version '%s'", kVersionLabel,
            getString(gHost->host, kOfxPropName, 0, "?").c_str(),
            getString(gHost->host, kOfxPropVersionLabel, 0, "?").c_str());
    return kOfxStatOK;
}

static OfxStatus describe(OfxImageEffectHandle effect) {
    OfxPropertySetHandle props = nullptr;
    gEffect->getPropertySet(effect, &props);
    gProp->propSetString(props, kOfxPropLabel, 0, "StrokeScribe Test");
    gProp->propSetString(props, kOfxImageEffectPluginPropGrouping, 0, "StrokeScribe");
    gProp->propSetString(props, kOfxPropPluginDescription, 0,
                         "Test effect: a hand draws a line over the clip. Writes a diagnostics log to "
                         "%LOCALAPPDATA%\\StrokeScribe\\ofx-test.log.");
    gProp->propSetString(props, kOfxImageEffectPropSupportedContexts, 0, kOfxImageEffectContextFilter);
    gProp->propSetString(props, kOfxImageEffectPropSupportedContexts, 1, kOfxImageEffectContextGeneral);
    gProp->propSetString(props, kOfxImageEffectPropSupportedPixelDepths, 0, kOfxBitDepthByte);
    gProp->propSetString(props, kOfxImageEffectPropSupportedPixelDepths, 1, kOfxBitDepthShort);
    gProp->propSetString(props, kOfxImageEffectPropSupportedPixelDepths, 2, kOfxBitDepthFloat);
    gProp->propSetInt(props, kOfxImageEffectPropSupportsMultipleClipDepths, 0, 0);
    gProp->propSetInt(props, kOfxImageEffectPropSupportsTiles, 0, 0);
    gProp->propSetInt(props, kOfxImageEffectPropTemporalClipAccess, 0, 0);
    gProp->propSetString(props, kOfxImageEffectPluginRenderThreadSafety, 0, kOfxImageEffectRenderFullySafe);
    gProp->propSetInt(props, kOfxImageEffectPluginPropHostFrameThreading, 0, 0);
    return kOfxStatOK;
}

static void defineDouble(OfxParamSetHandle set, const char *name, const char *label, const char *hint,
                         double def, double lo, double hi) {
    OfxPropertySetHandle p = nullptr;
    gParam->paramDefine(set, kOfxParamTypeDouble, name, &p);
    gProp->propSetString(p, kOfxPropLabel, 0, label);
    gProp->propSetString(p, kOfxParamPropHint, 0, hint);
    gProp->propSetDouble(p, kOfxParamPropDefault, 0, def);
    gProp->propSetDouble(p, kOfxParamPropMin, 0, lo);
    gProp->propSetDouble(p, kOfxParamPropMax, 0, hi);
    gProp->propSetDouble(p, kOfxParamPropDisplayMin, 0, lo);
    gProp->propSetDouble(p, kOfxParamPropDisplayMax, 0, hi);
}

static OfxStatus describeInContext(OfxImageEffectHandle effect, OfxPropertySetHandle inArgs) {
    std::string context = getString(inArgs, kOfxImageEffectPropContext, 0, "?");
    OfxPropertySetHandle clip = nullptr;
    gEffect->clipDefine(effect, kOfxImageEffectSimpleSourceClipName, &clip);
    gProp->propSetString(clip, kOfxImageEffectPropSupportedComponents, 0, kOfxImageComponentRGBA);
    gProp->propSetString(clip, kOfxImageEffectPropSupportedComponents, 1, kOfxImageComponentRGB);
    gProp->propSetString(clip, kOfxImageEffectPropSupportedComponents, 2, kOfxImageComponentAlpha);
    gProp->propSetInt(clip, kOfxImageClipPropOptional, 0, context == kOfxImageEffectContextGeneral ? 1 : 0);
    gProp->propSetInt(clip, kOfxImageEffectPropSupportsTiles, 0, 0);
    gEffect->clipDefine(effect, kOfxImageEffectOutputClipName, &clip);
    gProp->propSetString(clip, kOfxImageEffectPropSupportedComponents, 0, kOfxImageComponentRGBA);
    gProp->propSetString(clip, kOfxImageEffectPropSupportedComponents, 1, kOfxImageComponentRGB);
    gProp->propSetString(clip, kOfxImageEffectPropSupportedComponents, 2, kOfxImageComponentAlpha);
    gProp->propSetInt(clip, kOfxImageEffectPropSupportsTiles, 0, 0);

    OfxParamSetHandle set = nullptr;
    gEffect->getParamSet(effect, &set);
    defineDouble(set, "drawTime", "Draw time (s)", "Seconds the hand takes to draw the whole line.", 4, .2, 120);
    defineDouble(set, "lineWidth", "Line width", "Line width in pixels at full size.", 6, 1, 60);
    defineDouble(set, "handSize", "Hand size", "Hand height as a share of the frame height.", .45, .05, 1.5);
    OfxPropertySetHandle p = nullptr;
    gParam->paramDefine(set, kOfxParamTypeRGB, "inkColour", &p);
    gProp->propSetString(p, kOfxPropLabel, 0, "Ink colour");
    gProp->propSetDouble(p, kOfxParamPropDefault, 0, .15);
    gProp->propSetDouble(p, kOfxParamPropDefault, 1, .21);
    gProp->propSetDouble(p, kOfxParamPropDefault, 2, .29);
    gParam->paramDefine(set, kOfxParamTypeBoolean, "showHand", &p);
    gProp->propSetString(p, kOfxPropLabel, 0, "Show the hand");
    gProp->propSetInt(p, kOfxParamPropDefault, 0, 1);
    gParam->paramDefine(set, kOfxParamTypeChoice, "shape", &p);
    gProp->propSetString(p, kOfxPropLabel, 0, "Line");
    gProp->propSetString(p, kOfxParamPropChoiceOption, 0, "Handwriting wave");
    gProp->propSetString(p, kOfxParamPropChoiceOption, 1, "Spiral");
    gProp->propSetString(p, kOfxParamPropChoiceOption, 2, "Star");
    gProp->propSetInt(p, kOfxParamPropDefault, 0, 0);
    gParam->paramDefine(set, kOfxParamTypeBoolean, "writeLog", &p);
    gProp->propSetString(p, kOfxPropLabel, 0, "Write diagnostics log");
    gProp->propSetInt(p, kOfxParamPropDefault, 0, 1);
    logLine("describe in context '%s'", context.c_str());
    return kOfxStatOK;
}

static OfxStatus render(OfxImageEffectHandle effect, OfxPropertySetHandle inArgs) {
    auto started = std::chrono::steady_clock::now();
    OfxTime time = getDouble(inArgs, kOfxPropTime, 0, 0);
    int win[4] = {0, 0, 0, 0};
    gProp->propGetIntN(inArgs, kOfxImageEffectPropRenderWindow, 4, win);
    double rs[2] = {1, 1};
    gProp->propGetDoubleN(inArgs, kOfxImageEffectPropRenderScale, 2, rs);

    OfxImageClipHandle outClip = nullptr, srcClip = nullptr;
    gEffect->clipGetHandle(effect, kOfxImageEffectOutputClipName, &outClip, nullptr);
    gEffect->clipGetHandle(effect, kOfxImageEffectSimpleSourceClipName, &srcClip, nullptr);
    OfxPropertySetHandle outImg = nullptr, srcImg = nullptr;
    if (!outClip || gEffect->clipGetImage(outClip, time, nullptr, &outImg) != kOfxStatOK || !outImg)
        return kOfxStatFailed;
    if (srcClip) gEffect->clipGetImage(srcClip, time, nullptr, &srcImg);

    OfxImage dst = describeImage(outImg), src = describeImage(srcImg);
    OfxStatus status = kOfxStatOK;
    Params params;
    double fps = 0, start = 0, end = 0;
    try {
        params = readParams(effect, time);
        OfxPropertySetHandle effectProps = nullptr, outClipProps = nullptr;
        gEffect->getPropertySet(effect, &effectProps);
        gEffect->clipGetPropertySet(outClip, &outClipProps);
        fps = getDouble(outClipProps, kOfxImageEffectPropFrameRate, 0, 0);
        if (fps <= 0) fps = getDouble(effectProps, kOfxImageEffectPropFrameRate, 0, 25);
        start = getDouble(effectProps, kOfxImageEffectPropFrameRange, 0, 0);
        end = getDouble(effectProps, kOfxImageEffectPropFrameRange, 1, 0);
        double seconds = (time - start) / std::max(1.0, fps);
        double progress = seconds / params.drawSeconds;

        if (!dst.ok) throw 1;
        int wx1 = std::max(win[0], dst.x1), wy1 = std::max(win[1], dst.y1);
        int wx2 = std::min(win[2], dst.x2), wy2 = std::min(win[3], dst.y2);
        if (wx2 <= wx1 || wy2 <= wy1) throw 2;
        Canvas canvas;
        readInto(canvas, src, wx1, wy1, wx2, wy2);
        float tipX = 0, tipY = 0;
        drawStroke(canvas, params, progress, (float)rs[0], tipX, tipY);
        if (progress > 0 && progress < 1) drawHand(canvas, params, tipX, tipY);
        writeFrom(canvas, dst, wx1, wy1, wx2, wy2);
    } catch (...) {
        // Never fail the host: pass the clip through unchanged (or leave black).
        try {
            if (dst.ok && src.ok && dst.comps == src.comps && dst.depth == src.depth) {
                int bytes = (std::min(dst.x2, src.x2) - std::max(dst.x1, src.x1)) * dst.comps * dst.depth;
                for (int y = std::max(dst.y1, src.y1); y < std::min(dst.y2, src.y2) && bytes > 0; ++y)
                    std::memcpy(pixelAddr(dst, std::max(dst.x1, src.x1), y), pixelAddr(src, std::max(dst.x1, src.x1), y), bytes);
            }
        } catch (...) {
        }
        status = kOfxStatOK;
    }
    if (srcImg) gEffect->clipReleaseImage(srcImg);
    gEffect->clipReleaseImage(outImg);

    long n = ++gRenderCount;
    if (params.log && (n <= 40 || n % 50 == 0)) {
        double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
        logLine("render #%ld time=%.3f range=[%.1f,%.1f] fps=%.3f window=[%d,%d,%d,%d] scale=%.3f "
                "out=%dx%d comps=%d depth=%d src=%s %.1f ms",
                n, time, start, end, fps, win[0], win[1], win[2], win[3], rs[0],
                dst.x2 - dst.x1, dst.y2 - dst.y1, dst.comps, dst.depth, src.ok ? "yes" : "no", ms);
    }
    return status;
}

static OfxStatus mainEntry(const char *action, const void *handle, OfxPropertySetHandle inArgs,
                           OfxPropertySetHandle) {
    try {
        OfxImageEffectHandle effect = (OfxImageEffectHandle)handle;
        if (std::strcmp(action, kOfxActionLoad) == 0) return onLoad();
        if (std::strcmp(action, kOfxActionUnload) == 0) return kOfxStatOK;
        if (std::strcmp(action, kOfxActionDescribe) == 0) return describe(effect);
        if (std::strcmp(action, kOfxImageEffectActionDescribeInContext) == 0) return describeInContext(effect, inArgs);
        if (std::strcmp(action, kOfxImageEffectActionRender) == 0) return render(effect, inArgs);
        if (std::strcmp(action, kOfxActionCreateInstance) == 0) {
            logLine("instance created");
            return kOfxStatOK;
        }
        if (std::strcmp(action, kOfxActionDestroyInstance) == 0) return kOfxStatOK;
    } catch (...) {
        logLine("unexpected error in action %s", action ? action : "?");
        return kOfxStatFailed;
    }
    return kOfxStatReplyDefault;
}

static void setHost(OfxHost *host) { gHost = host; }

static OfxPlugin gPlugin = {kOfxImageEffectPluginApi, 1, kPluginId, 0, 1, setHost, mainEntry};

extern "C" {
OfxExport int OfxGetNumberOfPlugins(void) { return 1; }
OfxExport OfxPlugin *OfxGetPlugin(int nth) { return nth == 0 ? &gPlugin : nullptr; }
}
