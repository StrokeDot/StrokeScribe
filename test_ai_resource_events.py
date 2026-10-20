"""Real loopback WebSocket/HTTP protocol fixture; no model inference."""
import base64,copy,hashlib,json,os,struct,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_source_ai_lifecycle import APP
from create_image_dialog import AIWorker
import ai_engine

class ProtocolTests(unittest.TestCase):
    def run_protocol(self,sampler,disconnect=False):
        workflow={'1':{'class_type':'UNETLoader','inputs':{'unet_name':'fixture.safetensors'}},
            '2':{'class_type':sampler,'inputs':{'seed':123,'steps':8,'cfg':1.}},
            '4':{'class_type':'SaveImage','inputs':{'images':['2',0]}}}
        original=copy.deepcopy(workflow)
        finished=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def reply(self,payload):
                raw=json.dumps(payload).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def send_event(self,kind,**data):
                raw=json.dumps({'type':kind,'data':dict(prompt_id='fixture-prompt',**data)}).encode()
                frame=b'\x81'+(bytes([len(raw)]) if len(raw)<126 else b'\x7e'+struct.pack('!H',len(raw)))+raw
                try:self.server.ws.sendall(frame)
                except OSError:pass
            def do_GET(self):
                if self.path.startswith('/ws'):
                    key=self.headers['Sec-WebSocket-Key']
                    accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                    self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade')
                    self.send_header('Sec-WebSocket-Accept',accept);self.end_headers();self.wfile.flush()
                    self.server.ws=self.connection
                    self.server.ws_path=self.path
                    finished.wait(10);self.close_connection=True;return
                self.server.polls+=1
                count=self.server.polls
                if count==1:self.send_event('progress',node='2',value=0,max=8)
                elif count==2:
                    if disconnect:
                        try:self.server.ws.sendall(b'\x88\x00')
                        except OSError:pass
                    else:self.send_event('progress',node='2',value=4,max=8)
                elif count==3 and not disconnect:self.send_event('executing',node='4')
                if count>=4:self.reply({'fixture-prompt':{'outputs':{'4':{'images':[{'filename':'result.png'}]}}}})
                else:
                    __import__('time').sleep(.15);self.reply({})
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/prompt':
                    self.server.submitted=data
                    self.send_event('executing',node='1')
                    self.send_event('progress',node='1',value=100,max=100)
                    self.reply({'prompt_id':'fixture-prompt'})
                else:self.reply({})
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'STROKESCRIBE_CONFIG_DIR':folder}):
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;server.polls=0
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            engine=ai_engine.Engine();engine.port=server.server_port;engine.paths.output=Path(folder)
            engine.proc=SimpleNamespace(pid=os.getpid(),poll=lambda:None)
            from PIL import Image
            Image.new('RGBA',(2,2),(50,100,150,255)).save(Path(folder)/'result.png')
            events=[];results=[]
            worker=AIWorker('generate');worker.progress.connect(lambda percent,text:events.append((percent,text)))
            worker.done.connect(results.append)
            try:
                with patch.object(engine,'start'):
                    worker._generate(engine,workflow,None)
                APP.processEvents()
                self.assertEqual(server.submitted['prompt'],original)
                self.assertIn(server.submitted['client_id'],server.ws_path)
                self.assertEqual(results,[str(Path(folder)/'result.png')])
                self.assertTrue(any('Loading model' in text and percent==-1 for percent,text in events))
                self.assertFalse(any('sampling 100%' in text.lower() for _,text in events),'Loader 100% leaked as sampling')
                if disconnect:
                    self.assertTrue(any('exact stage unavailable' in text for _,text in events))
                else:
                    self.assertTrue(any(percent==50 and 'sampling' in text.lower() for percent,text in events),events)
                    self.assertTrue(any('Saving result' in text for _,text in events),events)
                self.assertEqual(events[-1],(100,'Completed'))
            finally:
                engine.flush_diagnostics(2);finished.set();server.shutdown();server.server_close();thread.join(2)
    def test_qwen_sampler_progress_and_save(self):
        self.run_protocol('KSampler')
    def test_flux_sampler_progress_and_save(self):
        self.run_protocol('SamplerCustomAdvanced')
    def test_disconnected_stage_stream_keeps_http_generation_working(self):
        self.run_protocol('KSampler',disconnect=True)
