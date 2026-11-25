"""Compact video export regression tests.

The FFmpeg checks explicitly request libvpx-vp9 for decoding: FFmpeg's native
VP9 decoder may silently strip alpha even from valid WebM alpha videos.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from engine import encode_webm, import_svg

APP=QApplication.instance() or QApplication([])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'FFmpeg and ffprobe are required to validate alpha')
class CompressedExportTests(unittest.TestCase):
    def make_frames(self, folder):
        for i in range(8):
            image=Image.new('RGBA',(128,72),(0,0,0,0))
            draw=ImageDraw.Draw(image)
            draw.rectangle((25+i,12,95,55),fill=(235,115,50,255))
            image.save(folder/f'frame_{i:06d}.png')

    def test_webm_alpha_codec_and_real_decoded_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            self.make_frames(folder)
            output=encode_webm(folder,fps=12,quality=28)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size,0)
            probe=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
                '-show_entries','stream=codec_name:stream_tags=alpha_mode','-of','json',
                str(output)])
            video=json.loads(probe)['streams'][0]
            self.assertEqual(video['codec_name'],'vp9')
            self.assertEqual(video.get('tags',{}).get('alpha_mode'),'1')
            data=subprocess.check_output(['ffmpeg','-hide_banner','-loglevel','error',
                '-c:v','libvpx-vp9','-i',str(output),'-frames:v','1',
                '-pix_fmt','rgba','-f','rawvideo','-'])
            self.assertEqual(len(data),128*72*4)
            self.assertEqual(data[3],0,'Outside the artwork must stay transparent')
            self.assertGreater(data[(30*128+60)*4+3],240,
                               'Filled artwork must remain opaque')

    def test_successful_video_export_removes_only_temporary_pngs(self):
        from app import Exporter
        drawing=import_svg(Path(__file__).parent/'samples'/'drawing.svg')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'video-export'
            worker=Exporter(drawing,folder,dict(duration=.3,fps=8,width=128,
                             height=72),False,True,28,False)
            success=[]; failure=[]
            worker.done.connect(success.append)
            worker.failed.connect(failure.append)
            worker.run()
            self.assertFalse(failure,str(failure))
            self.assertEqual(len(success),1)
            self.assertTrue((folder/'animation_vp9_alpha.webm').is_file())
            self.assertTrue((folder/'sequence.json').is_file())
            self.assertEqual(list(folder.glob('frame_*.png')),[])

    def test_mp4_export_on_chosen_background(self):
        from app import Exporter
        drawing=import_svg(Path(__file__).parent/'samples'/'drawing.svg')
        for background,rgb in (('white',(255,255,255)),('dark',(0x24,0x2D,0x3B))):
            with self.subTest(background=background), tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp)/'mp4-export'
                worker=Exporter(drawing,folder,dict(duration=.3,fps=8,width=128,
                                 height=72),False,False,28,False,
                                 mp4=True,mp4_background=background)
                errors=[]; worker.failed.connect(errors.append)
                worker.run()
                self.assertFalse(errors,str(errors))
                output=folder/f'animation_{background}_background.mp4'
                self.assertTrue(output.is_file())
                probe=json.loads(subprocess.check_output(['ffprobe','-v','error',
                    '-select_streams','v:0','-count_frames','-show_entries',
                    'stream=codec_name,width,height,nb_read_frames','-of','json',
                    str(output)]))['streams'][0]
                self.assertEqual(probe['codec_name'],'h264')
                self.assertEqual((probe['width'],probe['height']),(128,72))
                frames=len(list(folder.glob('frame_*.png'))) or None
                self.assertIsNone(frames,'PNGs removed after a successful MP4')
                self.assertEqual(int(probe['nb_read_frames']),
                                 json.loads((folder/'sequence.json').read_text())['frames'])
                # First frame is empty: every pixel is the background color.
                data=subprocess.check_output(['ffmpeg','-hide_banner','-loglevel','error',
                    '-i',str(output),'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'])
                for channel,want in zip(data[:3],rgb):
                    self.assertLessEqual(abs(channel-want),4)

    def test_png_only_export_keeps_frames(self):
        from app import Exporter
        drawing=import_svg(Path(__file__).parent/'samples'/'drawing.svg')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'png-only'
            worker=Exporter(drawing,folder,dict(duration=.3,fps=8,width=128,
                             height=72),False,False,28,False)
            errors=[]
            worker.failed.connect(errors.append)
            worker.run()
            self.assertFalse(errors,str(errors))
            self.assertTrue(list(folder.glob('frame_*.png')))
            self.assertTrue((folder/'sequence.json').exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
