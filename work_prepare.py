"""Generate build icon and preserve installed dependency license texts."""
from pathlib import Path
import importlib.metadata as md
import shutil
from PIL import Image, ImageDraw
root=Path(__file__).resolve().parent
work=root/'work';work.mkdir(exist_ok=True)
img=Image.new('RGBA',(256,256),(0,0,0,0));d=ImageDraw.Draw(img)
d.rounded_rectangle((0,0,255,255),radius=64,fill='#217965')
for x,y,dx,dy in [(68,96,0,-28),(68,68,32,0),(188,96,0,-28),(188,68,-32,0),
                  (68,160,0,28),(68,188,32,0),(188,160,0,28),(188,188,-32,0),
                  (100,116,56,0),(100,144,40,0)]:d.line((x,y,x+dx,y+dy),fill='white',width=14)
img.save(work/'shizi.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
dest=root/'outputs'/'拾字'/'licenses';dest.mkdir(parents=True,exist_ok=True)
for dist in md.distributions():
    name=dist.metadata['Name']
    for file in dist.files or []:
        if any(token in str(file).lower() for token in ['license','copying','notice']) and not str(file).endswith('.py'):
            source=Path(dist.locate_file(file))
            if source.is_file():
                target=dest/name/str(file).replace('../','').replace('..\\','')
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    if name.lower() in ['pyside6-essentials','pyside6_essentials','shiboken6','rapidocr-onnxruntime','onnxruntime','opencv-python','numpy','pillow']:
        p=dest/name/'PACKAGE_METADATA.txt';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(dist.read_text('METADATA') or '',encoding='utf-8')
(root/'requirements-lock.txt').write_text('\n'.join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in md.distributions()))+'\n',encoding='utf-8')
for f in (root/'docs'/'licenses').glob('*'):
    if f.is_file():shutil.copy2(f,dest/f.name)
for name in ['README.md','第三方说明.md','LICENSE','requirements-lock.txt']:
    if (root/name).exists():shutil.copy2(root/name,root/'outputs'/'拾字'/name)
