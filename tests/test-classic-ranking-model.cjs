'use strict';
// Actual Python producer -> actual browser validator, with fictional input only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {execFileSync}=require('node:child_process'),{webcrypto,createHash}=require('node:crypto');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'output/app.js'),'utf8');
const program=`import sys,json,tempfile,runpy,copy
sys.path[:0]=['tools','tests'];import classic_model_v1 as m,weekly_selected_rankings as r,weekly_adaptive_overlay as o
from pathlib import Path
from test_classic_build_pair_v1 import retained_classic_source
from reliability import atomic_json
t=runpy.run_path('tests/test_weekly_selected_rankings.py');board,doc=t['fixture']();doc['rows']=[]
legacy=t['make'](board,doc)
with tempfile.TemporaryDirectory()as directory:
 old_pointer=r.write_public(legacy,directory,atomic_json,clock=lambda:t['PERSIST'])
 board['execution_model']=m.contract(retained_classic_source(Path(directory)/'retained-classic-source'))
 for p in board['players']:p['reference_model']=m.MODEL
 doc['display_board_sha256']=doc['canonical_board_sha256']=o.digest(board)
 current=t['make'](board,doc);pointer=r.write_public(current,directory,atomic_json,clock=lambda:t['PERSIST'])
 for p in board['players']:p['reference_model']=m.ORIGINAL_MODEL
 doc['display_board_sha256']=doc['canonical_board_sha256']=o.digest(board)
 frozen=t['make'](board,doc,now='2031-10-25T18:00:00Z',previous=legacy,previous_receipt=old_pointer)
 frozen_pointer=r.write_public(frozen,directory,atomic_json,clock=lambda:'2031-10-25T18:00:01Z')
 r.validate_document(frozen,frozen_pointer,board,o.digest(board),doc,root=directory)
 frozen_board=copy.deepcopy(board);frozen_doc=copy.deepcopy(doc)
 for p in board['players']:p['reference_model']=m.MODEL
 doc['display_board_sha256']=doc['canonical_board_sha256']=o.digest(board)
 print(json.dumps(dict(board=board,doc=doc,ranking=current,pointer=pointer,frozen_board=frozen_board,frozen_doc=frozen_doc,frozen=frozen,frozen_pointer=frozen_pointer)))`;
const fixture=JSON.parse(execFileSync(process.env.PYTHON||'python3',['-B','-c',program],{cwd:root}));
const helper=require('../output/weekly-adaptive-overlay.js');
const functions=['loadWeeklyOverlayBound','selectedRankingPolicy','rankingCanonical','compareSelectedRankingItems','validateSelectedRankings'].map(name=>{
 const found=source.match(new RegExp('(?:async )?function '+name+'\\([^]*?\\n\\}'));assert(found,name);return found[0];
}).join('\n');
const context={S:{data:fixture.board},crypto:webcrypto,TextEncoder,performance:require('node:perf_hooks').performance,setTimeout,clearTimeout,
  fetch:()=>{throw Error('unexpected network request');}};vm.createContext(context);vm.runInContext(functions,context);
// Mock only HTTP transport; the actual bounded loader hashes and validates bytes.
async function loadFixtureOverlay(doc,board){
 const body=context.rankingCanonical(doc),hash=createHash('sha256').update(body).digest('hex');
 const pointer={schema_version:'weekly-adaptive-overlay-pointer-v1',path:'data/weekly-adaptive/'+hash+'.json',sha256:hash,bytes:Buffer.byteLength(body),display_board_sha256:doc.display_board_sha256};
 context.fetch=async url=>new Response(url==='data/weekly-adaptive-overlay.json'?JSON.stringify(pointer):url===pointer.path?body:'not found',
  {status:url==='data/weekly-adaptive-overlay.json'||url===pointer.path?200:404});
 return context.loadWeeklyOverlayBound(board,doc.display_board_sha256,helper);
}
(async()=>{
 let checks=0;
 let overlay=await loadFixtureOverlay(fixture.doc,fixture.board);
 await context.validateSelectedRankings(fixture.ranking,fixture.pointer,fixture.board,overlay);checks++;
 const items=Object.values(fixture.ranking.picks).flat();
 assert(items.length>0&&items.every(x=>x.forecast_source==='CURRENT_BASELINE'&&x.model_version==='sleeper-matchup-classic-fg-identity-v1'));checks++;
 const bad=structuredClone(fixture.ranking);const first=Object.values(bad.picks).flat()[0];first.forecast_source='R0_FALLBACK';first.model_version=null;
 await assert.rejects(()=>context.validateSelectedRankings(bad,fixture.pointer,fixture.board,overlay),/Ranking fallback/);checks++;
 context.S.data=fixture.frozen_board;
 overlay=await loadFixtureOverlay(fixture.frozen_doc,fixture.frozen_board);
 await context.validateSelectedRankings(fixture.frozen,fixture.frozen_pointer,fixture.frozen_board,overlay);checks++;
 assert(Object.values(fixture.frozen.picks).flat().every(x=>x.forecast_source==='R0_FALLBACK'&&x.model_version===null));checks++;
 console.log(JSON.stringify({state:'PASS',checks,HTTP:0,scope:'Retained Classic1 baseline typed separately; frozen original R0 membership/model retained'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
