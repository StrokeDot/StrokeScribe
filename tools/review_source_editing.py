"""Remote review artifacts; representative art, no user artwork or AI weights."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PySide6.QtGui import QImage
from test_artwork_workflow import WorkflowFixture,APP
from test_artwork_pairing import pair
from test_artwork_rendering import render_options,frame,rgba
from source_editor import SourceEditor
from projects import save
from engine import export_frames
from image_painting import original_frame
import numpy as np

def main():
    output=Path('samples/source-editing');output.mkdir(parents=True,exist_ok=True)
    fixture=WorkflowFixture();fixture.setUp()
    try:
        w=fixture.w
        original,guide=pair(fixture.tmp.name)
        w.image_detail.setCurrentText('Low')
        w.request_artwork(str(guide),kind='lineart',original=str(original),placement='add')
        fixture.wait_import()
        # Same source replacement route as the inspector/painting editor.
        assert w.replace_paint_source(str(original))
        for stage in ('draw','paint'):
            editor=SourceEditor(w,stage);editor.show();APP.processEvents()
            assert editor.grab().save(str(output/(stage+'-source-editor.png')))
            editor.reject();editor.deleteLater();APP.processEvents()
        w.grab().save(str(output/'workspace.png'))
        o=render_options(w);drawing=w.drawing
        for name,f in [('drawing',.5/2.2)]+[(f'paint-{percent}',(1+percent/100)/2.2) for percent in (25,50,75,100)]:
            frame(drawing,o,f).save(str(output/(name+'.png')))
        np.testing.assert_array_equal(rgba(frame(drawing,o,1)),rgba(original_frame(drawing,o['final_image'],320,180)))
        options={k:v for k,v in o.items() if k not in ('audio','workers','layers','erase','camera_zoom','offset','entrance','pause','sound_files','overlays')}
        options['fps']=12
        export_frames(drawing,output/'transparent-frames',**options)
        files=sorted((output/'transparent-frames').glob('frame_*.png'))
        for index in (0,len(files)//3,len(files)*2//3,len(files)-1):
            np.testing.assert_array_equal(rgba(QImage(str(files[index]))),rgba(frame(drawing,o,index/(len(files)-1))))
        assert QImage(str(files[-1])).pixelColor(0,0).alpha()==0
        save(output/'source-workflow-review',w.project_state())
        print('Source editors captured; changed-source drawing/paint/final and exported alpha frames match.')
    finally:fixture.tearDown()

if __name__=='__main__':main()
