"""Wholly fictional transport used only by explicit subprocess test setup."""
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

PLAYERS={
    'home-qb':dict(full_name='FICTIONAL Home QB',position='QB',team='AAA',active=True),
    'home-k':dict(full_name='FICTIONAL Home K',position='K',team='AAA',active=True),
    'away-qb':dict(full_name='FICTIONAL Away QB',position='QB',team='BBB',active=True),
    'away-k':dict(full_name='FICTIONAL Away K',position='K',team='BBB',active=True),
}
ROWS=[dict(player_id=pid,team=team,opponent='BBB'if team=='AAA'else'AAA',stats=stats)
    for pid,team,stats in [
        ('home-qb','AAA',dict(gp=1,pts_ppr=18,pass_yd=250,pass_td=2)),
        ('home-k','AAA',dict(gp=1,pts_ppr=0,fgm=3,xpm=2)),
        ('away-qb','BBB',dict(gp=1,pts_ppr=22,pass_yd=250,pass_td=3)),
        ('away-k','BBB',dict(gp=1,pts_ppr=0,fgm=1,xpm=3))]]

def value(url,params):
    path=urlsplit(url).path
    if path=='/v1/state/nfl':return dict(season='2099',week=2,season_type='regular')
    if path=='/v1/players/nfl':return copy.deepcopy(PLAYERS)
    if '/stats/nfl/'in path or '/projections/nfl/'in path:return copy.deepcopy(ROWS)
    if path.endswith('/scoreboard'):
        return dict(events=[dict(id='fictional-game',date='2099-10-25T17:00:00Z',
            status=dict(type=dict(state='pre',completed=False,shortDetail='Scheduled')),
            competitions=[dict(status=dict(type=dict(state='pre',completed=False,shortDetail='Scheduled')),
                competitors=[dict(homeAway=side,score='',team=dict(id=str(i),abbreviation=team))for i,side,team in[(1,'home','AAA'),(2,'away','BBB')]])])])
    if path.endswith('/lines/available'):return []
    if path.endswith('/injuries'):return dict(injuries=[])
    if path.endswith('/teams'):return dict(sports=[])
    if path.endswith('/odds')or path.endswith('/propBets'):return dict(items=[])
    if path.endswith('/depthcharts'):return {}
    raise AssertionError('FICTIONAL_UNSUPPORTED_REQUEST: '+path)

def install():
    import requests,socket
    def denied(*a,**k):raise AssertionError('SOCKET_NETWORK_DISABLED_PAIR_TEST')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=denied
    def response(session,method,url,**kwargs):
        body=value(url,kwargs.get('params'))
        counter=os.environ.get('CLASSIC_FIXTURE_COUNTER')
        if counter:
            with Path(counter).open('a')as stream:stream.write('FICTIONAL_TRANSPORT_CALL\n')
        return type('FictionalResponse',(),dict(raise_for_status=lambda self:None,json=lambda self:copy.deepcopy(body)))()
    requests.sessions.Session.request=response
