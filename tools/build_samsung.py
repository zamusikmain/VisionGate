"""Package only an allowlist of application code and compiled UI; never datasets/reports."""
import argparse
import hashlib
from pathlib import Path
import zipfile
import os


def build(output):
    root=Path(__file__).resolve().parents[1];output=Path(output).resolve()
    if not (root/'frontend/dist/index.html').is_file():raise ValueError('Build frontend first')
    files=[]
    for folder,extensions in [('backend',{'.py'}),('tools',{'.py','.ps1','.mjs'}),('tests',{'.py'}),('config',{'.json'}),('docs',{'.md'}),('frontend/dist',{'.html','.js','.css','.svg'}),('frontend/src',{'.ts','.tsx','.css'})]:
        base=root/folder
        for directory,subdirs,names in os.walk(base,followlinks=False):
            subdirs[:]=[n for n in subdirs if n not in {'node_modules','__pycache__'} and not (Path(directory)/n).is_symlink()]
            for name in names:
                p=Path(directory)/name
                if p.is_file() and not p.is_symlink() and p.suffix in extensions:files.append(p)
    files.extend(root/p for p in ('requirements.txt','requirements-samsung-export.txt','requirements-samsung-models.txt','README.md','start-samsung.ps1'))
    files.extend(root/'frontend'/p for p in ('package.json','package-lock.json','tsconfig.json','vite.config.ts','index.html'))
    if output in files:raise ValueError('Output must not overwrite source')
    output.parent.mkdir(parents=True,exist_ok=True)
    # No dependency directories, junctions, original images, private reports or secrets.
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(files)):z.write(p,p.relative_to(root).as_posix())
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        assert not any(n.startswith(('reports/','dataset/','holdout/')) or '/node_modules/' in n for n in z.namelist())
    print('Local application bundle:',output)
    print('SHA-256:',hashlib.sha256(output.read_bytes()).hexdigest())
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path('reports/samsung-build/VisionGate-Samsung-local.zip'))
    build(parser.parse_args().output)
