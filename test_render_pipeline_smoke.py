"""Phase 5: a small real animation pipeline, through scene transition, audio and encoders.

Uses synthetic artwork and does not overwrite user files. External editor
compatibility (including Filmora) still needs a human Windows acceptance test.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from engine import import_svg
from frame_render import compose_frame
from export_job import encode_outputs
from scenes import transition_frame

APP=QApplication.instance() or QApplication([])
HERE=Path(__file__).parent


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'real video export needs FFmpeg and ffprobe')
class CompleteRenderPipelineTests(unittest.TestCase):
    def options(self, offset=(0,0)):
        return dict(width=160,height=90,duration=.35,fade_duration=.15,hold_duration=.0,
                    final_image=None,thickness=1.,hand=None,hand_scale=.25,
                    anchor=(.1,.1),reveal_mode='adaptive',brush_width=.14,
                    painting_hand=None,stroke_spacing=.55,artwork_scale=.7,offset=offset)

    def test_real_svg_scene_move_audio_and_both_video_encoders(self):
        drawing=import_svg(HERE/'samples'/'drawing.svg')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            frames=[]
            a=compose_frame(drawing, .7, self.options())
            b=compose_frame(drawing, 1., self.options((.18,0)))
            frames.append(compose_frame(drawing, 0., self.options()))
            frames.append(a)
            frames.append(transition_frame(a,b,'Pan right',.35))
            frames.append(transition_frame(a,b,'Pan right',.7))
            frames.append(compose_frame(drawing,.55,self.options((.18,0))))
            frames.append(b)
            for index, image in enumerate(frames):
                self.assertEqual((image.width(),image.height()),(160,90))
                self.assertTrue(image.save(str(root/f'frame_{index:06d}.png')),
                                'real render frame should be a saved PNG')
            # Encode on a dark background for MP4, preserve alpha in WebM.
            # WAV is intentionally quiet and deterministic; its presence
            # verifies the audio mux without requiring a microphone.
            audio=root/'narration.wav'
            with wave.open(str(audio),'wb') as out:
                out.setnchannels(2)
                out.setsampwidth(2)
                out.setframerate(44100)
                out.writeframes(b'\x00\x00\x00\x00'*44100)
            (root/'sequence.json').write_text(json.dumps({
                'width':160,'height':90,'frames':len(frames),'fps':8
            }))
            summary=encode_outputs(root,8,webm=True,webm_quality=28,
                                   mp4=True,mp4_background='dark',
                                   audio=audio,keep_png=True)
            self.assertIn('Saved:',summary)
            webm=root/'animation_vp9_alpha.webm'
            mp4=root/'animation_dark_background.mp4'
            for output in (webm,mp4):
                self.assertTrue(output.is_file())
                self.assertGreater(output.stat().st_size,1000)
                probe=json.loads(subprocess.check_output([
                    'ffprobe','-v','error','-show_entries','stream=codec_type,codec_name',
                    '-of','json',str(output)]))
                streams=probe.get('streams',[])
                self.assertIn('video',{s['codec_type'] for s in streams})
                self.assertIn('audio',{s['codec_type'] for s in streams})
            self.assertTrue(all((root/f'frame_{i:06d}.png').exists()
                                for i in range(len(frames))),
                            'Retain source frames until the user asks to remove them')
            info=json.loads(subprocess.check_output([
                'ffprobe','-v','error','-select_streams','v:0',
                '-show_entries','stream=codec_name:stream_tags=alpha_mode',
                '-of','json',str(webm)]))['streams'][0]
            self.assertEqual(info['codec_name'],'vp9')
            self.assertEqual(str(info.get('tags',{}).get('alpha_mode')),'1')
            # The WebM alpha tag alone is not proof that the pixel data
            # survived the encode/decode round-trip. FFmpeg's native VP9
            # decoder can discard alpha, so explicitly use libvpx-vp9.
            rgba=subprocess.check_output([
                'ffmpeg','-v','error','-c:v','libvpx-vp9',
                '-i',str(webm),'-map','0:v:0','-frames:v',str(len(frames)),
                '-f','rawvideo','-pix_fmt','rgba','pipe:1'])
            self.assertEqual(len(rgba),160*90*4*len(frames))
            alpha=rgba[3::4]
            self.assertEqual(min(alpha),0,
                             'The WebM must preserve fully transparent pixels.')
            self.assertGreater(max(alpha),127,
                               'The WebM must also contain visible artwork.')

    def test_intermediate_scene_transition_keeps_canvas_transparency(self):
        drawing=import_svg(HERE/'samples'/'drawing.svg')
        a=compose_frame(drawing,1.,self.options())
        b=compose_frame(drawing,0.,self.options((.2,0)))
        result=transition_frame(a,b,'Camera move',.5)
        self.assertEqual(result.pixelColor(80,0).alpha(),0)
        self.assertEqual((result.width(),result.height()),(160,90))


if __name__=='__main__':
    unittest.main(verbosity=2)
