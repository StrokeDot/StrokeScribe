"""Observe only events for our prompt; stdout percentages are never sampler proof."""
import json,math,time

SAMPLERS={'KSampler','KSamplerAdvanced','SamplerCustom','SamplerCustomAdvanced'}
SAVERS={'SaveImage','SaveAudio','SaveAnimatedWEBP','SaveAnimatedPNG'}
class Activity:
    def __init__(self,prompt_id,workflow):
        self.prompt_id=prompt_id;self.workflow=workflow
        self.stage='preparing';self.percent=None;self.node=None;self.observed=False
        self.updated=self.started=time.monotonic()
    def event(self,event):
        if not isinstance(event,dict):return
        data=event.get('data')
        if not isinstance(data,dict) or data.get('prompt_id')!=self.prompt_id:return
        kind=event.get('type');node=data.get('node',self.node)
        node=str(node) if node is not None else None
        cls=(self.workflow.get(node) or {}).get('class_type')
        if kind=='progress' and cls in SAMPLERS:
            try:value,total=float(data['value']),float(data['max'])
            except (KeyError,ValueError,TypeError):return
            if not math.isfinite(value) or not math.isfinite(total) or total<=0 or not 0<=value<=total:return
            self.node=node;self.percent=int(100*value/total);self.stage='sampling'
        elif kind=='executing' and node is not None:
            self.node=node;self.percent=None
            self.stage='saving' if cls in SAVERS else 'preparing'
        elif kind not in ('execution_start','execution_cached','executed','execution_success','execution_error','execution_interrupted'):
            return
        self.observed=True;self.updated=time.monotonic()
    def label(self,alive=True,stall_seconds=30):
        elapsed=time.monotonic()-self.started
        idle=time.monotonic()-self.updated
        if alive and idle>=stall_seconds:
            return f'Engine still running — no progress reported for {int(idle)}s ({int(elapsed)}s elapsed). It may be loading or offloading.'
        if self.stage=='sampling' and self.percent is not None:return f'Generating image — sampling {self.percent}%'
        if self.stage=='saving':return 'Saving result…'
        if not self.observed:return 'Loading model / preparing generation — exact stage unavailable…'
        return 'Loading model / preparing generation…'

class EventStream:
    def __init__(self,port,client_id):
        import websocket
        self.websocket=websocket
        self.socket=websocket.create_connection(f'ws://127.0.0.1:{int(port)}/ws?clientId={client_id}',
                    timeout=1.,http_no_proxy=['127.0.0.1','localhost'],suppress_origin=True)
        self.socket.settimeout(.001)
        self.failed=False
    def drain(self,activity):
        for _ in range(64):
            try:
                raw=self.socket.recv()
                if raw=='':self.failed=True;return
                if isinstance(raw,str) and len(raw)<=262144:
                    try:activity.event(json.loads(raw))
                    except (ValueError,TypeError):pass
            except self.websocket.WebSocketTimeoutException:return
            except Exception:
                self.failed=True;return
    def close(self):
        try:self.socket.close(timeout=.1)
        except Exception:pass
