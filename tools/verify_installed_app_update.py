"""Remote CI probe: update disposable .58/.59 installs to this source candidate.

Never run against a real user installation. Baselines come from repository
commits; all application files, user-data sentinels and settings are temporary.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
BASELINES=(
    ('cd4ff3d298f9653239de45e447b84fa4c9249d80','0.5.3-experimental.58'),
    ('c23fd37f9a37468192b49d5fdd2fb40d008c84f9','0.5.3-experimental.59'),
)

def source(ref,path):
    return subprocess.check_output(['git','show',f'{ref}:{path}'],cwd=ROOT)

def main():
    from version import APP_VERSION
    with tempfile.TemporaryDirectory(prefix='strokescribe-update-probe-') as tmp:
        area=Path(tmp)
        package=area/'candidate.zip'
        # GitHub zipball uses repository blobs, not checkout-converted CRLF
        # files. Match those exact archive bytes on both Windows and Linux.
        package.write_bytes(subprocess.check_output(
            ['git','archive','--format=zip','--prefix=candidate/','HEAD'],cwd=ROOT))
        for index,(ref,old_version) in enumerate(BASELINES):
            installed=area/f'installed-{index}';installed.mkdir()
            for name in ('version.py','requirements.txt','updater.py','create_image_dialog.py'):
                (installed/name).write_bytes(source(ref,name))
            sentinels={
                installed/'runtime'/'keep.txt':b'private-runtime-sentinel',
                installed/'Projects'/'keep.ssp':b'user-project-sentinel',
                area/f'settings-{index}'/'keep.json':b'user-settings-sentinel',
                area/f'AI-models-{index}'/'keep.bin':b'user-model-sentinel',
            }
            for path,data in sentinels.items():
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            module_name=f'baseline_updater_{index}'
            spec=importlib.util.spec_from_file_location(module_name,installed/'updater.py')
            updater=importlib.util.module_from_spec(spec);sys.modules[module_name]=updater
            spec.loader.exec_module(updater)
            if updater.current_version(installed)!=old_version:
                raise AssertionError('Wrong baseline installed')
            if not updater.is_newer(APP_VERSION,old_version):
                raise AssertionError('Candidate will not be offered as a newer update')
            result=updater.apply_zip(package,installed)
            if result['version']!=APP_VERSION or result['requirements_changed']:
                raise AssertionError('Update version/dependencies differ from the expected candidate')
            for path,data in sentinels.items():
                if path.read_bytes()!=data:
                    raise AssertionError('Update changed preserved user/runtime data')
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',
                     STROKESCRIBE_CONFIG_DIR=str(area/f'settings-{index}'))
            check="""from pathlib import Path
import ai_engine
from version import APP_VERSION
from PySide6.QtWidgets import QApplication
from ai_models import Hardware
from create_image_dialog import CreateImageDialog
settings=ai_engine.load_settings()
settings['root']=str(Path.cwd()/'disposable-ai-engine')
ai_engine.save_settings(settings)
app=QApplication([])
dialog=CreateImageDialog(hardware=Hardware('CI test GPU',16,64,True))
dialog.show()
dialog.check_updates_button.click()
app.processEvents()
assert dialog.updates_panel.isVisible()
assert 'Demonstration' in ' '.join(x.text() for x in dialog.updates_panel.findChildren(__import__('PySide6.QtWidgets',fromlist=['QLabel']).QLabel))
dialog.close()
print('Updated dialog loads:',APP_VERSION)
"""
            subprocess.run([sys.executable,'-c',check],cwd=installed,env=env,check=True)
            restored=updater.roll_back(installed)
            if restored!=old_version or updater.current_version(installed)!=old_version:
                raise AssertionError('Rollback did not restore the installed baseline')
            for path,data in sentinels.items():
                if path.read_bytes()!=data:
                    raise AssertionError('Rollback changed preserved user/runtime data')
            print(json.dumps(dict(baseline=old_version,candidate=APP_VERSION,
                                  update='passed',dialog='passed',rollback='passed',
                                  dependencies_changed=False,user_data_preserved=True)))
    print('Installed app update compatibility: PASSED')

if __name__=='__main__':
    main()
