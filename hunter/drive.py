"""Google Drive through the official Codex app-server, using existing ChatGPT auth."""
import base64
import json
import subprocess
import time
from . import db,model
from .worker import codex_binary,clean_env
from .process_events import EventLines

class Drive:
    def __init__(self,cancelled=lambda:False):
        self.cancelled=cancelled;self.id=0;self.mutable=set();self.readable=set();self.process=None
    def __enter__(self):
        self.process=subprocess.Popen([codex_binary(),'app-server','-c','features.apps=true','-c','features.plugins=true','-c','features.shell_tool=false'],
          stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,env=clean_env(),cwd=db.DATA)
        self.lines=EventLines(self.process.stdout)
        try:return self.connect()
        except BaseException:
            self.__exit__();raise
    def connect(self):
        self.request('initialize',{'clientInfo':{'name':'job_hunter','title':'Job Hunter','version':'0.3.0'},'capabilities':{'experimentalApi':True}})
        self.send({'method':'initialized','params':{}})
        apps=self.request('app/installed',{'forceRefresh':True}).get('apps',[])
        app=next((a for a in apps if a.get('runtimeName')=='Google Drive' and a.get('enabled') and a.get('callable')),None)
        if not app:raise ValueError('Connect Google Drive in ChatGPT, then check the connection in Job Hunter.')
        self.app_id=app['id']
        result=self.request('thread/start',{'ephemeral':True,'cwd':str(db.DATA),'sandbox':'read-only','config':{'features.shell_tool':False,'features.multi_agent':False}})
        self.thread=result['thread']['id']
        inventory=self.request('mcpServerStatus/list',{'threadId':self.thread,'detail':'toolsAndAuthOnly','serverName':'codex_apps','limit':100})
        tools=next((s.get('tools',{}) for s in inventory.get('data',[]) if s['name']=='codex_apps'),{})
        required=('get_document','copy_file','batch_update_document','fetch')
        if not all('google_drive.'+tool in tools for tool in required):raise ValueError('The connected Google Drive does not expose native document editing. Reconnect the Google Drive plugin in ChatGPT.')
        return self
    def __exit__(self,*_):
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
    def send(self,message):self.process.stdin.write(json.dumps(message)+'\n');self.process.stdin.flush()
    def request(self,method,params,timeout=120):
        self.id+=1;id=self.id;self.send({'id':id,'method':method,'params':params});deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if self.cancelled():raise model.Cancelled()
            ready,line=self.lines.next()
            if not ready:continue
            if line is None:raise ValueError('The Google Drive connection closed. Your document checkpoint is saved.')
            message=json.loads(line)
            if message.get('id')==id:
                if 'error' in message:raise ValueError('Google Drive could not complete the operation: '+str(message['error'].get('message','Connection failed')))
                return message.get('result',{})
            if 'id' in message and 'method' in message:
                # A managed approval must remain a human handover; never accept unseen requests.
                self.send({'id':message['id'],'error':{'code':-32000,'message':'Resolve this connection or approval in ChatGPT, then resume Job Hunter.'}})
                raise ValueError('Google Drive requires an approval in ChatGPT. Resolve it, then resume this saved step.')
        raise ValueError('Google Drive timed out. Your document checkpoint is saved; re-check the copy before resuming.')
    def call(self,tool,args):
        result=self.request('mcpServer/tool/call',{'threadId':self.thread,'server':'codex_apps','tool':'google_drive.'+tool,'arguments':args})
        if result.get('isError'):raise ValueError('Google Drive reported an error; inspect the saved document step before resuming.')
        if result.get('structuredContent') is not None:return result['structuredContent']
        content=result.get('content',[])
        text='\n'.join(item.get('text','') for item in content if item.get('type')=='text')
        try:return json.loads(text)
        except ValueError:raise ValueError('Google Drive returned an unreadable result. Inspect this saved document step.')
    def get(self,id):
        if id not in self.readable|self.mutable:raise ValueError('Document is outside this preparation task')
        return self.call('get_document',{'document_id':id})
    def copy(self,id,title):
        if id not in self.readable:raise ValueError('Select the role’s native template first')
        result=self.call('copy_file',{'url':'https://docs.google.com/document/d/'+id,'new_title':title})
        copied=result.get('id') or result.get('file',{}).get('id')
        if not copied or copied==id:raise ValueError('The native copy could not be verified. Inspect Google Drive before retrying.')
        self.mutable.add(copied);return copied
    def update(self,id,requests,revision):
        if id not in self.mutable:raise ValueError('Only this task’s native copy can be edited')
        return self.call('batch_update_document',{'document_id':id,'requests':requests,'write_control':{'requiredRevisionId':revision}})
    def pdf(self,id,path):
        if id not in self.mutable:raise ValueError('Only this task’s native copy can be exported')
        result=self.call('fetch',{'url':'https://docs.google.com/document/d/'+id,'download_raw_file':True,'raw_export_mime_type':'application/pdf','include_base64':True})
        # Only decode an explicit provider binary field, never an arbitrary model string.
        def binary(value):
            if isinstance(value,dict):
                for key in ('b64_string','base64','content_base64','file_base64','data_base64'):
                    if isinstance(value.get(key),str):return value[key]
                for child in value.values():
                    found=binary(child)
                    if found:return found
            if isinstance(value,list):
                for child in value:
                    found=binary(child)
                    if found:return found
        encoded=binary(result)
        if not encoded:raise ValueError('Google Drive did not return the complete PDF bytes. The native copy is retained.')
        raw=base64.b64decode(encoded,validate=True)
        if not raw.startswith(b'%PDF-') or len(raw)>10_000_000:raise ValueError('Native PDF export failed its integrity check')
        path.write_bytes(raw);return path
