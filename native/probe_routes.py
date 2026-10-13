import sys
from PyQt5.QtCore import QCoreApplication,QTimer
from nova import Task
app=QCoreApplication([])
provider=sys.argv[1];model={'provider':sys.argv[2],'model':sys.argv[3]}
t=Task(provider,[{'role':'user','content':'Reply with only NOVA ready. Do not use tools.'}],'nova-model-probe',model)
failed=[]
def success(text):print('OK',provider,model['model'],text[:140]);app.quit()
def error(text):failed.append(text);print('FAILED',provider,model['model'],text[:200]);app.quit()
t.result.connect(success);t.error.connect(error);t.start();QTimer.singleShot(130000,app.quit);app.exec_();t.cancel();t.wait(5000)
sys.exit(1 if failed else 0)
