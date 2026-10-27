"""Fictional first-use/current/history traces for the retained-FG cache contract."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'pull'),str(ROOT/'tools')]
import build
import gamemodel

TRACE={}
TEAMS={'home-qb':('QB','AAA'),'home-k':('K','AAA'),'away-qb':('QB','BBB'),'away-k':('K','BBB')}
GAME=[dict(id='fictional-game',home='AAA',away='BBB',odds=dict(spread=1,total=44))]
ROWS=[dict(player_id=pid,team=team,opponent='BBB'if team=='AAA'else'AAA',stats=stats)
      for pid,team,stats in [
          ('home-qb','AAA',dict(gp=1,pts_ppr=20,pass_td=2)),
          ('home-k','AAA',dict(gp=1,pts_ppr=0,fgm=3,xpm=2)),
          ('away-qb','BBB',dict(gp=1,pts_ppr=24,pass_td=3)),
          ('away-k','BBB',dict(gp=1,pts_ppr=0,fgm=1,xpm=3))]]
OLD={r['player_id']:dict(team=r['team'],opp=r['opponent'],stats={k:v for k,v in r['stats'].items()if k!='fgm'})for r in ROWS}
OLD_BYTES=(json.dumps(OLD,sort_keys=True,indent=2)+'\n').encode()

def raw_points(stats):
    return gamemodel.rollup({pid:entry['stats']for pid,entry in stats.items()},TEAMS)

class RetainedFGCacheTests(unittest.TestCase):
    def old_cache(self,root,season,week):
        path=root/f'stats_{season}_{week:02d}.json';path.write_bytes(OLD_BYTES);return path

    def test_first_historical_read_ignores_legacy_cache_and_preserves_its_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.old_cache(root,2098,18)
            with patch.object(build,'CACHE',root),patch.object(build.sources,'week_stats',return_value=copy.deepcopy(ROWS))as source:
                stats=build.week_stats(2098,18,refresh=False)
            source.assert_called_once_with(2098,18)
            self.assertEqual(build.STATS_CACHE_VERSION,'stat-keys-presence-fgm-v2')
            self.assertEqual(old.read_bytes(),OLD_BYTES)
            saved=root/build.STATS_CACHE_VERSION/'stats_2098_18.json'
            self.assertEqual(json.loads(saved.read_text()),stats)
            self.assertEqual(stats['home-k']['stats']['fgm'],3)
            self.assertEqual(raw_points(OLD),{'AAA':14,'BBB':21})
            self.assertEqual(raw_points(stats),{'AAA':23,'BBB':24})
            old_spread=gamemodel.finish(GAME,raw_points(OLD),22)['fictional-game']['spread']
            new_spread=gamemodel.finish(GAME,raw_points(stats),22)['fictional-game']['spread']
            self.assertEqual((old_spread,new_spread),(8.8,1.0))
            TRACE['first_historical_read']=dict(old_raw={'AAA':14,'BBB':21},new_raw={'AAA':23,'BBB':24},
                old_spread=old_spread,new_spread=new_spread,source_calls=source.call_count,
                old_cache_bytes_preserved=True,season=2098,week=18,
                rollup_scope='Direct diagnostic using actual normalized cached values; not a rewrite of an archived game forecast')

    def test_current_actual_and_projection_take_independent_full_normalization_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=self.old_cache(root,2099,1)
            with patch.object(build,'CACHE',root),\
                 patch.object(build.sources,'week_stats',return_value=copy.deepcopy(ROWS))as actual_source,\
                 patch.object(build.sources,'week_projections',return_value=copy.deepcopy(ROWS))as projection_source:
                actual=build.week_stats(2099,1,refresh=True)
                projection=build.projections(2099,1)
            self.assertEqual(old.read_bytes(),OLD_BYTES)
            actual_source.assert_called_once_with(2099,1)
            projection_source.assert_called_once_with(2099,1)
            self.assertEqual(raw_points(actual),{'AAA':23,'BBB':24})
            self.assertEqual(gamemodel.rollup(projection,TEAMS),{'AAA':23,'BBB':24})
            self.assertEqual(gamemodel.finish(GAME,gamemodel.rollup(projection,TEAMS),22)['fictional-game']['spread'],1.0)
            TRACE['current_actual_and_projection']=dict(actual_fgm=[actual['home-k']['stats']['fgm'],actual['away-k']['stats']['fgm']],
                projection_fgm=[projection['home-k']['fgm'],projection['away-k']['fgm']],
                actual_raw=raw_points(actual),projection_raw=gamemodel.rollup(projection,TEAMS),old_cache_bytes_preserved=True)

    def test_load_stats_through_uses_new_contract_for_prior_and_current_seasons(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);keys=[(2098,1),(2098,2),(2099,1),(2099,2)]
            originals=[self.old_cache(root,*key)for key in keys]
            with patch.object(build,'CACHE',root),patch.object(build,'REGULAR_SEASON_WEEKS',2),\
                 patch.object(build.sources,'week_stats',return_value=copy.deepcopy(ROWS))as source:
                history=build.load_stats_through(2099,2,refresh_from=2)
            self.assertEqual(list(history),keys)
            self.assertEqual(source.call_count,4)
            for key,old in zip(keys,originals):
                self.assertEqual(history[key]['home-k']['stats']['fgm'],3)
                self.assertEqual(old.read_bytes(),OLD_BYTES)
            TRACE['load_stats_through']=dict(periods=[list(key)for key in keys],source_calls=4,
                unrefreshed_legacy_periods_recollected=True,old_cache_bytes_preserved=True)

    def test_warm_new_cache_reuses_its_contract_and_forced_refresh_preserves_legacy(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);old=self.old_cache(root,2098,18)
            with patch.object(build,'CACHE',root):
                with patch.object(build.sources,'week_stats',return_value=copy.deepcopy(ROWS)):
                    first=build.week_stats(2098,18,refresh=False)
                with patch.object(build.sources,'week_stats',side_effect=AssertionError('unexpected refresh')):
                    self.assertEqual(build.week_stats(2098,18,refresh=False),first)
                revised=copy.deepcopy(ROWS);revised[1]['stats']['fgm']=4
                with patch.object(build.sources,'week_stats',return_value=revised):
                    self.assertEqual(build.week_stats(2098,18,refresh=True)['home-k']['stats']['fgm'],4)
            self.assertEqual(old.read_bytes(),OLD_BYTES)

    def test_missing_source_cannot_fall_back_to_legacy_cache(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);old=self.old_cache(root,2098,18)
            with patch.object(build,'CACHE',root),patch.object(build.sources,'week_stats',side_effect=RuntimeError('FICTIONAL_SOURCE_UNAVAILABLE')):
                with self.assertRaisesRegex(RuntimeError,'FICTIONAL_SOURCE_UNAVAILABLE'):
                    build.week_stats(2098,18,refresh=False)
            self.assertEqual(old.read_bytes(),OLD_BYTES)
            self.assertFalse((root/build.STATS_CACHE_VERSION/'stats_2098_18.json').exists())
            TRACE['unavailable_source']=dict(old_cache_used=False,old_cache_bytes_preserved=True,new_cache_created=False)

    def test_unreported_total_is_not_reconstructed_by_the_cache_version(self):
        missing=copy.deepcopy(ROWS)
        for row in missing:row['stats'].pop('fgm',None)
        with tempfile.TemporaryDirectory()as directory:
            with patch.object(build,'CACHE',Path(directory)),\
                 patch.object(build.sources,'week_stats',return_value=missing),\
                 patch.object(build.sources,'week_projections',return_value=missing):
                stats=build.week_stats(2098,18,refresh=False);projection=build.projections(2099,1)
            self.assertNotIn('fgm',stats['home-k']['stats'])
            self.assertNotIn('fgm',projection['home-k'])
            self.assertEqual(raw_points(stats),{'AAA':14,'BBB':21})
            self.assertEqual(gamemodel.rollup(projection,TEAMS),{'AAA':14,'BBB':21})
            TRACE['missing_upstream_total']=dict(reconstructed=False,raw={'AAA':14,'BBB':21},claim='Retention cannot establish an absent upstream total')

if __name__=='__main__':unittest.main()
