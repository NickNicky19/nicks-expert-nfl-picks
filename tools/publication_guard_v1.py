"""Bind one existing Pages writer to its trigger, published Git head and assets.

This fence detects supersession; Git and Pages are not one atomic transaction.
The existing release owner must serialize source landing with the same writer.
No merge, force push, scheduler, deployment or job cancellation is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

VERSION="website-publication-fence-v1"
REPOSITORY="NickNicky19/nicks-expert-nfl-picks"
ROOT=Path(__file__).resolve().parents[1]
MAX_FILES=50000
MAX_BYTES=512<<20


class FenceError(ValueError):pass


def require(ok,code):
    if not ok:raise FenceError(code)


def canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
def sha(body):return hashlib.sha256(body).hexdigest()


def git(root,*args):
    return subprocess.check_output(["git","--no-replace-objects","-c","core.hooksPath=/dev/null",*args],
                                   cwd=root,stderr=subprocess.DEVNULL)


def current_main(root):
    subprocess.run(["git","-c","core.hooksPath=/dev/null","fetch","--no-tags","origin","main"],
                   cwd=root,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
    return git(root,"rev-parse","origin/main").decode().strip()


def context(root,env):
    source=env.get("GITHUB_SHA","")
    require(env.get("GITHUB_ACTIONS")=="true" and env.get("GITHUB_REPOSITORY")==REPOSITORY
        and env.get("GITHUB_REF")=="refs/heads/main"
        and env.get("GITHUB_EVENT_NAME") in {"push","schedule","workflow_dispatch"}
        and re.fullmatch(r"[1-9][0-9]{0,19}",env.get("GITHUB_RUN_ID",""))
        and re.fullmatch(r"[1-9][0-9]{0,3}",env.get("GITHUB_RUN_ATTEMPT",""))
        and re.fullmatch(r"[a-f0-9]{40}",source)
        and env.get("GITHUB_WORKFLOW_SHA")==source,"GENUINE_MATCHED_WORKFLOW_CONTEXT")
    return dict(repository=REPOSITORY,run_id=env["GITHUB_RUN_ID"],run_attempt=env["GITHUB_RUN_ATTEMPT"],trigger_source_sha=source)


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=8<<20,"BOUNDED_FENCE_RECEIPT")
    raw=path.read_bytes()
    def pairs(items):
        out={}
        for key,value in items:
            require(key not in out,"DUPLICATE_FENCE_KEY");out[key]=value
        return out
    result=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(FenceError("NONFINITE_FENCE_JSON")))
    require(canonical(result)==raw,"EXACT_FENCE_ENCODING")
    return result


def create(path,value):
    require(not any(p.is_symlink() for p in (path,*path.parents)),"FENCE_SYMLINK")
    path.parent.mkdir(parents=True,exist_ok=True)
    body=canonical(value)
    require(len(body)<=8<<20,"FENCE_RECEIPT_CAP")
    descriptor,temp=tempfile.mkstemp(prefix=".publication-fence-",dir=path.parent)
    try:
        with os.fdopen(descriptor,"wb") as stream:
            stream.write(body);stream.flush();os.fsync(stream.fileno())
        try:os.link(temp,path)
        except FileExistsError:require(path.read_bytes()==body,"IMMUTABLE_FENCE_CONFLICT")
    finally:Path(temp).unlink(missing_ok=True)


def inventory(root):
    output=root/"output"
    require(output.is_dir() and not output.is_symlink(),"OUTPUT_ROOT_REQUIRED")
    tracked=set(git(root,"ls-files","-z","--","output").decode().split("\0"))
    files=[];total=0
    for path in sorted(output.rglob("*")):
        require(not path.is_symlink(),"OUTPUT_SYMLINK")
        if path.is_dir():continue
        name=path.relative_to(root).as_posix()
        require(name in tracked and path.is_file(),"UNTRACKED_OR_SPECIAL_OUTPUT")
        size=path.stat().st_size;total+=size
        require(len(files)<MAX_FILES and total<=MAX_BYTES,"FINITE_PAGES_OUTPUT_BOUND")
        digest=hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda:stream.read(1<<20),b""):digest.update(block)
        require(path.stat().st_size==size,"OUTPUT_CHANGED_WHILE_HASHING")
        files.append(dict(path=name,bytes=size,sha256=digest.hexdigest()))
    require(files and not git(root,"status","--porcelain","--untracked-files=all","--","output"),"CLEAN_COMMITTED_OUTPUT_REQUIRED")
    return dict(files=len(files),bytes=total,manifest_sha256=sha(canonical(files)))


def begin(root,receipt,env):
    identity=context(root,env);head=git(root,"rev-parse","HEAD").decode().strip()
    require(head==identity["trigger_source_sha"]==current_main(root),"STALE_TRIGGER_OR_CHECKOUT")
    require(not git(root,"status","--porcelain","--untracked-files=all"),"CLEAN_TRIGGER_CHECKOUT_REQUIRED")
    create(receipt,dict(schema_version=VERSION+"-begin",**identity))
    return dict(state="TRIGGER_SOURCE_MATCHED",source_sha=head)


def classic_generated(root,source,head):
    """Only create-only derived captures/state; response tapes never qualify."""
    changes=git(root,"diff","--name-status","--no-renames","-z",source,head).decode().split("\0")
    for status,name in zip(changes[::2],changes[1::2]):
        if name.startswith("data/current-classic/"):
            require(status=="A" and re.fullmatch(r"data/current-classic/[0-9]{4}/w[0-9]{2}/[a-f0-9]{64}\.json\.gz",name),"CLASSIC_CAPTURE_CREATE_ONLY")
        elif name.startswith("data/classic-r0-shadow/"):
            if name=="data/classic-r0-shadow/latest.json":
                require(status in {"A","M"},"CLASSIC_SHADOW_POINTER_REQUIRED")
                continue
            match=re.fullmatch(r"data/classic-r0-shadow/[a-f0-9]{64}/(.+)",name)
            require(match is not None,"CLASSIC_SHADOW_DERIVED_SCOPE")
            suffix=match.group(1)
            derived=(suffix in {"PAIR.json","ORIGINAL_SOURCE.json","native.json.gz"}
                or re.fullmatch(r"state/output/data/(?:week\.json|meta\.json|track_record\.json|(?:archive|weeks)/[^/]+\.json)",suffix)
                or re.fullmatch(r"state/data/cache/(?:stats_[0-9]{4}_[0-9]{2}\.json|espn_athletes\.json|injury_timeline\.json)",suffix))
            require(derived and status=="A","CLASSIC_SHADOW_CREATE_ONLY_DERIVED")


def sealed(root,receipt,env):
    first=read(receipt);identity=context(root,env)
    require(first==dict(schema_version=VERSION+"-begin",**identity),"EXACT_ORIGINAL_FENCE_REQUIRED")
    source=identity["trigger_source_sha"];head=git(root,"rev-parse","HEAD").decode().strip()
    require(head==current_main(root),"SUPERSEDED_PUBLISHED_HEAD")
    count=int(git(root,"rev-list","--count",source+".."+head))
    require(count in (0,1),"ONE_GENERATED_COMMIT_ONLY")
    if head!=source:
        require(git(root,"rev-parse",head+"^").decode().strip()==source,"SOURCE_PARENT_CHANGED")
        names=git(root,"diff","--name-only","-z",source,head).decode().split("\0")
        allowed=("output/data/","data/cache/","data/weekly-adaptive-audit/","data/forward/","data/history/",
                 "data/verification/","data/shadow/","data/offers/","data/outcomes/",
                 "data/current-classic/","data/classic-r0-shadow/")
        require(all(not name or name.startswith(allowed) for name in names),"GENERATED_COMMIT_CHANGED_SOURCE")
        classic_generated(root,source,head)
    result=dict(schema_version=VERSION+"-published",**identity,published_head_sha=head,output=inventory(root))
    create(receipt.with_suffix(".published.json"),result)
    return dict(state="PUBLISHED_SOURCE_AND_ASSETS_BOUND",published_head_sha=head,**result["output"])


def check(root,receipt,env,stage):
    original=read(receipt);identity=context(root,env)
    require(original==dict(schema_version=VERSION+"-begin",**identity),"EXACT_ORIGINAL_FENCE_REQUIRED")
    bound=read(receipt.with_suffix(".published.json"))
    require(set(bound)==set(identity)|{"schema_version","published_head_sha","output"}
        and bound["schema_version"]==VERSION+"-published"
        and all(bound[k]==v for k,v in identity.items()),"EXACT_PUBLISHED_FENCE_REQUIRED")
    require(git(root,"rev-parse","HEAD").decode().strip()==bound["published_head_sha"]==current_main(root),"SUPERSEDED_BEFORE_"+stage.upper())
    require(inventory(root)==bound["output"],"ASSETS_CHANGED_AFTER_PUBLICATION")
    return dict(state="PUBLICATION_FENCE_PASSED",stage=stage,published_head_sha=bound["published_head_sha"],**bound["output"])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation",choices=["begin","sealed","check"])
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--receipt",type=Path,required=True)
    parser.add_argument("--stage",choices=["upload","deploy","retry","postdeploy"],default="deploy")
    args=parser.parse_args()
    try:
        result=begin(args.root,args.receipt,os.environ) if args.operation=="begin" else sealed(args.root,args.receipt,os.environ) if args.operation=="sealed" else check(args.root,args.receipt,os.environ,args.stage)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as error:
        reason=str(error) if isinstance(error,FenceError) else "PUBLICATION_FENCE_FAILED"
        print(json.dumps(dict(state="PUBLICATION_REFUSED",reason=reason)));return 1


if __name__=="__main__":raise SystemExit(main())
