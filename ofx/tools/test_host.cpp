// A tiny OpenFX host for testing the StrokeScribe plugin without a video editor.
//   test_host PLUGIN.ofx OUTPUT_DIR
// Loads the plugin, describes it, renders frames in every pixel depth and a few
// odd cases (render window smaller than the image, negative row bytes, no
// source clip), checks nothing crashes, and writes PNGs to look at.
#include <cstdarg>
#include <cstdio>
#include <algorithm>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif
#include "ofxCore.h"
#include "ofxImageEffect.h"
#include "ofxParam.h"
#include "ofxProperty.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

struct Value { std::vector<std::string> s; std::vector<int> i; std::vector<double> d; std::vector<void *> p; };
struct PropSet { std::map<std::string, Value> v; };
static std::vector<std::unique_ptr<PropSet>> gSets;
static PropSet *newSet() { gSets.emplace_back(new PropSet); return gSets.back().get(); }
#define PS(h) ((PropSet *)(h))

template <class T> static void put(std::vector<T> &v, int i, T x) { if ((int)v.size() <= i) v.resize(i + 1); v[i] = x; }
static OfxStatus setS(OfxPropertySetHandle h, const char *n, int i, const char *x) { put(PS(h)->v[n].s, i, std::string(x)); return kOfxStatOK; }
static OfxStatus setI(OfxPropertySetHandle h, const char *n, int i, int x) { put(PS(h)->v[n].i, i, x); return kOfxStatOK; }
static OfxStatus setD(OfxPropertySetHandle h, const char *n, int i, double x) { put(PS(h)->v[n].d, i, x); return kOfxStatOK; }
static OfxStatus setP(OfxPropertySetHandle h, const char *n, int i, void *x) { put(PS(h)->v[n].p, i, x); return kOfxStatOK; }
static OfxStatus setSN(OfxPropertySetHandle h, const char *n, int c, const char *const *x) { for (int i = 0; i < c; ++i) setS(h, n, i, x[i]); return kOfxStatOK; }
static OfxStatus setIN(OfxPropertySetHandle h, const char *n, int c, const int *x) { for (int i = 0; i < c; ++i) setI(h, n, i, x[i]); return kOfxStatOK; }
static OfxStatus setDN(OfxPropertySetHandle h, const char *n, int c, const double *x) { for (int i = 0; i < c; ++i) setD(h, n, i, x[i]); return kOfxStatOK; }
static OfxStatus setPN(OfxPropertySetHandle h, const char *n, int c, void *const *x) { for (int i = 0; i < c; ++i) setP(h, n, i, x[i]); return kOfxStatOK; }
static OfxStatus getS(OfxPropertySetHandle h, const char *n, int i, char **x) {
    auto it = PS(h)->v.find(n); if (it == PS(h)->v.end() || (int)it->second.s.size() <= i) return kOfxStatErrUnknown;
    *x = (char *)it->second.s[i].c_str(); return kOfxStatOK; }
static OfxStatus getI(OfxPropertySetHandle h, const char *n, int i, int *x) {
    auto it = PS(h)->v.find(n); if (it == PS(h)->v.end() || (int)it->second.i.size() <= i) return kOfxStatErrUnknown;
    *x = it->second.i[i]; return kOfxStatOK; }
static OfxStatus getD(OfxPropertySetHandle h, const char *n, int i, double *x) {
    auto it = PS(h)->v.find(n); if (it == PS(h)->v.end() || (int)it->second.d.size() <= i) return kOfxStatErrUnknown;
    *x = it->second.d[i]; return kOfxStatOK; }
static OfxStatus getP(OfxPropertySetHandle h, const char *n, int i, void **x) {
    auto it = PS(h)->v.find(n); if (it == PS(h)->v.end() || (int)it->second.p.size() <= i) return kOfxStatErrUnknown;
    *x = it->second.p[i]; return kOfxStatOK; }
static OfxStatus getSN(OfxPropertySetHandle h, const char *n, int c, char **x) { for (int i = 0; i < c; ++i) if (getS(h, n, i, x + i)) return kOfxStatErrUnknown; return kOfxStatOK; }
static OfxStatus getIN(OfxPropertySetHandle h, const char *n, int c, int *x) { for (int i = 0; i < c; ++i) if (getI(h, n, i, x + i)) return kOfxStatErrUnknown; return kOfxStatOK; }
static OfxStatus getDN(OfxPropertySetHandle h, const char *n, int c, double *x) { for (int i = 0; i < c; ++i) if (getD(h, n, i, x + i)) return kOfxStatErrUnknown; return kOfxStatOK; }
static OfxStatus getPN(OfxPropertySetHandle h, const char *n, int c, void **x) { for (int i = 0; i < c; ++i) if (getP(h, n, i, x + i)) return kOfxStatErrUnknown; return kOfxStatOK; }
static OfxStatus reset(OfxPropertySetHandle, const char *) { return kOfxStatOK; }
static OfxStatus dim(OfxPropertySetHandle h, const char *n, int *c) { auto &v = PS(h)->v[n]; *c = (int)std::max(std::max(v.s.size(), v.i.size()), std::max(v.d.size(), v.p.size())); return kOfxStatOK; }
static OfxPropertySuiteV1 gProps = {setP, setS, setD, setI, setPN, setSN, setDN, setIN, getP, getS, getD, getI, getPN, getSN, getDN, getIN, reset, dim};

// Parameters: remember their defaults and answer with them.
struct Param { std::string type; PropSet *props; };
struct ParamSet { std::map<std::string, Param> params; };
static OfxStatus paramDefine(OfxParamSetHandle set, const char *type, const char *name, OfxPropertySetHandle *props) {
    PropSet *p = newSet(); ((ParamSet *)set)->params[name] = {type, p}; if (props) *props = (OfxPropertySetHandle)p; return kOfxStatOK; }
static OfxStatus paramGetHandle(OfxParamSetHandle set, const char *name, OfxParamHandle *h, OfxPropertySetHandle *props) {
    auto it = ((ParamSet *)set)->params.find(name); if (it == ((ParamSet *)set)->params.end()) return kOfxStatErrUnknown;
    *h = (OfxParamHandle)&it->second; if (props) *props = (OfxPropertySetHandle)it->second.props; return kOfxStatOK; }
static OfxStatus paramGetValueAtTime(OfxParamHandle h, OfxTime, ...) {
    Param *p = (Param *)h; va_list a; va_start(a, h);
    auto &d = p->props->v[kOfxParamPropDefault];
    if (p->type == kOfxParamTypeDouble) *va_arg(a, double *) = d.d.empty() ? 0 : d.d[0];
    else if (p->type == kOfxParamTypeRGB) { for (int i = 0; i < 3; ++i) *va_arg(a, double *) = (int)d.d.size() > i ? d.d[i] : 0; }
    else *va_arg(a, int *) = d.i.empty() ? 0 : d.i[0];
    va_end(a); return kOfxStatOK; }
static OfxStatus notImpl(...) { return kOfxStatErrUnsupported; }
static OfxParameterSuiteV1 gParams;

// Image effect: one effect with Source and Output clips.
struct Clip { PropSet *props; PropSet *image; };
struct Effect { PropSet *props; ParamSet params; std::map<std::string, Clip> clips; };
static OfxStatus getPropertySet(OfxImageEffectHandle e, OfxPropertySetHandle *p) { *p = (OfxPropertySetHandle)((Effect *)e)->props; return kOfxStatOK; }
static OfxStatus getParamSet(OfxImageEffectHandle e, OfxParamSetHandle *p) { *p = (OfxParamSetHandle) & ((Effect *)e)->params; return kOfxStatOK; }
static OfxStatus clipDefine(OfxImageEffectHandle e, const char *n, OfxPropertySetHandle *p) {
    auto &c = ((Effect *)e)->clips[n]; c.props = newSet(); c.image = nullptr; *p = (OfxPropertySetHandle)c.props; return kOfxStatOK; }
static OfxStatus clipGetHandle(OfxImageEffectHandle e, const char *n, OfxImageClipHandle *c, OfxPropertySetHandle *p) {
    auto it = ((Effect *)e)->clips.find(n); if (it == ((Effect *)e)->clips.end()) return kOfxStatErrBadIndex;
    *c = (OfxImageClipHandle)&it->second; if (p) *p = (OfxPropertySetHandle)it->second.props; return kOfxStatOK; }
static OfxStatus clipGetPropertySet(OfxImageClipHandle c, OfxPropertySetHandle *p) { *p = (OfxPropertySetHandle)((Clip *)c)->props; return kOfxStatOK; }
static OfxStatus clipGetImage(OfxImageClipHandle c, OfxTime, const OfxRectD *, OfxPropertySetHandle *img) {
    Clip *k = (Clip *)c; if (!k->image) return kOfxStatFailed; *img = (OfxPropertySetHandle)k->image; return kOfxStatOK; }
static OfxStatus clipReleaseImage(OfxPropertySetHandle) { return kOfxStatOK; }
static OfxImageEffectSuiteV1 gEffectSuite;

static const void *fetchSuite(OfxPropertySetHandle, const char *name, int) {
    if (!std::strcmp(name, kOfxPropertySuite)) return &gProps;
    if (!std::strcmp(name, kOfxParameterSuite)) return &gParams;
    if (!std::strcmp(name, kOfxImageEffectSuite)) return &gEffectSuite;
    return nullptr;
}

struct Buffer { std::vector<unsigned char> bytes; PropSet *props; };
static Buffer makeImage(int w, int h, const char *depth, const char *comps, bool flipRows, bool fill) {
    int ch = !std::strcmp(comps, kOfxImageComponentRGBA) ? 4 : !std::strcmp(comps, kOfxImageComponentRGB) ? 3 : 1;
    int bpc = !std::strcmp(depth, kOfxBitDepthFloat) ? 4 : !std::strcmp(depth, kOfxBitDepthShort) ? 2 : 1;
    Buffer b; b.bytes.assign((size_t)w * h * ch * bpc, 0); b.props = newSet();
    int row = w * ch * bpc;
    if (fill)
        for (int y = 0; y < h; ++y) for (int x = 0; x < w; ++x) for (int k = 0; k < ch; ++k) {
            double v = k == 3 ? 1.0 : (k == 0 ? .95 : k == 1 ? .93 : .88) - .1 * x / w;
            unsigned char *p = &b.bytes[(size_t)y * row + ((size_t)x * ch + k) * bpc];
            if (bpc == 1) *p = (unsigned char)(v * 255); else if (bpc == 2) *(unsigned short *)p = (unsigned short)(v * 65535); else *(float *)p = (float)v;
        }
    void *data = flipRows ? (void *)&b.bytes[(size_t)(h - 1) * row] : (void *)b.bytes.data();
    setP((OfxPropertySetHandle)b.props, kOfxImagePropData, 0, data);
    int bounds[4] = {0, 0, w, h}; setIN((OfxPropertySetHandle)b.props, kOfxImagePropBounds, 4, bounds);
    setI((OfxPropertySetHandle)b.props, kOfxImagePropRowBytes, 0, flipRows ? -row : row);
    setS((OfxPropertySetHandle)b.props, kOfxImageEffectPropPixelDepth, 0, depth);
    setS((OfxPropertySetHandle)b.props, kOfxImageEffectPropComponents, 0, comps);
    return b;
}

static void savePng(const Buffer &b, int w, int h, const char *depth, const char *comps, bool flipRows, const std::string &path) {
    int ch = !std::strcmp(comps, kOfxImageComponentRGBA) ? 4 : !std::strcmp(comps, kOfxImageComponentRGB) ? 3 : 1;
    int bpc = !std::strcmp(depth, kOfxBitDepthFloat) ? 4 : !std::strcmp(depth, kOfxBitDepthShort) ? 2 : 1;
    std::vector<unsigned char> out((size_t)w * h * 4);
    int row = w * ch * bpc;
    for (int y = 0; y < h; ++y) {
        int memRow = flipRows ? (h - 1 - y) : y;           // OFX row y (bottom = 0)
        for (int x = 0; x < w; ++x) for (int k = 0; k < 4; ++k) {
            double v = 1;
            if (k < ch || (ch == 1 && k == 3)) {
                int kk = ch == 1 ? 0 : k;
                const unsigned char *p = &b.bytes[(size_t)memRow * row + ((size_t)x * ch + kk) * bpc];
                v = bpc == 1 ? *p / 255.0 : bpc == 2 ? *(const unsigned short *)p / 65535.0 : *(const float *)p;
            }
            out[((size_t)(h - 1 - y) * w + x) * 4 + k] = (unsigned char)(std::min(1.0, std::max(0.0, v)) * 255);
        }
    }
    stbi_write_png(path.c_str(), w, h, 4, out.data(), w * 4);
}

int main(int argc, char **argv) {
    if (argc < 3) { std::fprintf(stderr, "usage: test_host PLUGIN OUTDIR\n"); return 2; }
    gParams = {}; gParams.paramDefine = paramDefine; gParams.paramGetHandle = paramGetHandle; gParams.paramGetValueAtTime = paramGetValueAtTime;
    gEffectSuite = {}; gEffectSuite.getPropertySet = getPropertySet; gEffectSuite.getParamSet = getParamSet;
    gEffectSuite.clipDefine = clipDefine; gEffectSuite.clipGetHandle = clipGetHandle; gEffectSuite.clipGetPropertySet = clipGetPropertySet;
    gEffectSuite.clipGetImage = clipGetImage; gEffectSuite.clipReleaseImage = clipReleaseImage;
#ifdef _WIN32
    HMODULE lib = LoadLibraryA(argv[1]); if (!lib) { std::fprintf(stderr, "cannot load plugin\n"); return 1; }
    auto count = (int (*)())GetProcAddress(lib, "OfxGetNumberOfPlugins");
    auto get = (OfxPlugin * (*)(int))GetProcAddress(lib, "OfxGetPlugin");
#else
    void *lib = dlopen(argv[1], RTLD_NOW); if (!lib) { std::fprintf(stderr, "cannot load plugin: %s\n", dlerror()); return 1; }
    auto count = (int (*)())dlsym(lib, "OfxGetNumberOfPlugins");
    auto get = (OfxPlugin * (*)(int))dlsym(lib, "OfxGetPlugin");
#endif
    if (!count || !get || count() != 1) { std::fprintf(stderr, "bad plugin exports\n"); return 1; }
    OfxPlugin *plugin = get(0);
    std::printf("plugin %s %d.%d api %s\n", plugin->pluginIdentifier, plugin->pluginVersionMajor, plugin->pluginVersionMinor, plugin->pluginApi);
    PropSet *hostProps = newSet();
    setS((OfxPropertySetHandle)hostProps, kOfxPropName, 0, "strokescribe.testhost");
    setS((OfxPropertySetHandle)hostProps, kOfxPropVersionLabel, 0, "1.0");
    static OfxHost host = {(OfxPropertySetHandle)hostProps, fetchSuite};
    plugin->setHost(&host);
    int failures = 0;
    auto act = [&](const char *a, Effect *e, PropSet *in) {
        OfxStatus s = plugin->mainEntry(a, e, (OfxPropertySetHandle)in, nullptr);
        if (s != kOfxStatOK && s != kOfxStatReplyDefault) { std::printf("  %s -> %d\n", a, s); ++failures; }
        return s;
    };
    act(kOfxActionLoad, nullptr, nullptr);
    Effect e; e.props = newSet();
    act(kOfxActionDescribe, &e, nullptr);
    PropSet *ctx = newSet(); setS((OfxPropertySetHandle)ctx, kOfxImageEffectPropContext, 0, kOfxImageEffectContextFilter);
    act(kOfxImageEffectActionDescribeInContext, &e, ctx);
    act(kOfxActionCreateInstance, &e, nullptr);
    setD((OfxPropertySetHandle)e.props, kOfxImageEffectPropFrameRange, 0, 0);
    setD((OfxPropertySetHandle)e.props, kOfxImageEffectPropFrameRange, 1, 240);
    setD((OfxPropertySetHandle)e.clips[kOfxImageEffectOutputClipName].props, kOfxImageEffectPropFrameRate, 0, 30);

    struct Case { const char *depth, *comps; bool flip, source, smallWindow; double time; const char *name; };
    Case cases[] = {
        {kOfxBitDepthByte, kOfxImageComponentRGBA, false, true, false, 0, "byte-start"},
        {kOfxBitDepthByte, kOfxImageComponentRGBA, false, true, false, 60, "byte-half"},
        {kOfxBitDepthShort, kOfxImageComponentRGBA, false, true, false, 30, "short-quarter"},
        {kOfxBitDepthFloat, kOfxImageComponentRGBA, false, true, false, 90, "float-three-quarters"},
        {kOfxBitDepthByte, kOfxImageComponentRGB, false, true, false, 60, "rgb-half"},
        {kOfxBitDepthByte, kOfxImageComponentAlpha, false, true, false, 60, "alpha-half"},
        {kOfxBitDepthByte, kOfxImageComponentRGBA, true, true, false, 60, "negative-rowbytes"},
        {kOfxBitDepthByte, kOfxImageComponentRGBA, false, false, false, 60, "no-source"},
        {kOfxBitDepthFloat, kOfxImageComponentRGBA, false, true, true, 60, "small-window"},
        {kOfxBitDepthByte, kOfxImageComponentRGBA, false, true, false, 200, "after-end"},
    };
    const int W = 960, H = 540;
    for (auto &c : cases) {
        Buffer src = makeImage(W, H, c.depth, c.comps, c.flip, true);
        Buffer dst = makeImage(W, H, c.depth, c.comps, c.flip, false);
        e.clips[kOfxImageEffectSimpleSourceClipName].image = c.source ? src.props : nullptr;
        e.clips[kOfxImageEffectOutputClipName].image = dst.props;
        PropSet *in = newSet();
        setD((OfxPropertySetHandle)in, kOfxPropTime, 0, c.time);
        int win[4] = {0, 0, W, H};
        if (c.smallWindow) { win[0] = 100; win[1] = 50; win[2] = 600; win[3] = 400; }
        setIN((OfxPropertySetHandle)in, kOfxImageEffectPropRenderWindow, 4, win);
        setD((OfxPropertySetHandle)in, kOfxImageEffectPropRenderScale, 0, 1);
        setD((OfxPropertySetHandle)in, kOfxImageEffectPropRenderScale, 1, 1);
        OfxStatus s = act(kOfxImageEffectActionRender, &e, in);
        std::printf("render %-22s -> %d\n", c.name, s);
        savePng(dst, W, H, c.depth, c.comps, c.flip, std::string(argv[2]) + "/" + c.name + ".png");
    }
    act(kOfxActionDestroyInstance, &e, nullptr);
    act(kOfxActionUnload, nullptr, nullptr);
    std::printf(failures ? "FAILED (%d)\n" : "OK\n", failures);
    return failures ? 1 : 0;
}
