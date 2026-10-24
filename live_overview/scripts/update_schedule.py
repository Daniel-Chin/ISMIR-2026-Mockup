#!/usr/bin/env python3
"""convert(): events.csv + papers.csv + session_assignment.csv -> schedule dict (used by build_miniconf.py)."""
import csv,json,re,sys,tempfile,os
from pathlib import Path
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
import csv_helpers as helper
from build_public_site import build
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from utils.shared import event_link  # noqa: E402  (same event pages as the miniconf calendar)

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames):raise ValueError(f'{path.name}: invalid headers')
        rows=list(reader)
        if any(None in r for r in rows):raise ValueError(f'{path.name}: malformed CSV row')
        return rows

def find_csv(folder,stem):
    exact=folder/(stem+'.csv')
    if exact.exists():return exact
    found=[p for p in folder.glob('*.csv') if re.fullmatch(re.escape(stem)+r'\s*\(\d+\)\.csv',p.name)]
    if len(found)!=1:raise ValueError(f'请在 {folder} 放入唯一的 {stem}.csv（也支持下载时的括号编号）。')
    return found[0]

EXTRA_EVENTS=ROOT/'extra-events.json'

def extra_events(conf,problem,path=EXTRA_EVENTS):
    """Events only on the Live Overview (extra-events.json), shaped like the CSV's.

    Their Zoom link is set on the backend's admin page, which later imports keep (same id,
    title and type), so headcounts work as for any other session.
    """
    if not path.exists():return []
    out=[]
    for item in json.loads(path.read_text(encoding='utf-8')).get('events',[]):
        key=helper.clean_text(item.get('id'));title=helper.clean_text(item.get('title'));category=helper.clean_text(item.get('category'))
        if not re.fullmatch(r'[a-z0-9-]{1,40}',key) or not title:problem(f'extra-events.json: missing id or title ({key!r})');continue
        typ=helper.event_type(title,category)
        if category.lower() in {'special','award nominee'}:typ='special'
        if category.lower()=='tutorials':typ='tutorial'
        tbd=not helper.clean_text(item.get('end'))
        try:
            start=helper.parse_local_datetime(item.get('date'),item.get('start'),conf['timezone'])
            # end_date (optional): an event over several days, e.g. a test event left open.
            end=(start+timedelta(days=1)).replace(hour=0,minute=0,second=0) if tbd else helper.parse_local_datetime(item.get('end_date') or item.get('date'),item.get('end'),conf['timezone'])
            if end<=start:end+=timedelta(days=1)
        except ValueError as error:
            problem(f'extra-events.json: {title} 时间无效: {error}');continue
        links={'slack':item['slack'].strip()} if urlsplit(item.get('slack','').strip()).scheme=='https' else {}
        event={'id':'event-'+key,'sourceEventId':key,'title':title,'type':typ,'category':category,'track':'main','startsAt':start.isoformat(),'endsAt':end.isoformat(),
               'links':links,'day':start.strftime('%A'),'dayNumber':None,'topic':helper.topic_from_event(typ,category),'summary':helper.clean_text(item.get('summary')),'organiser':''}
        if tbd:event['endTimeTBD']=True
        if item.get('speakers') is True:event['speakers']=True   # its webinar observer reports speakers too
        if item.get('debugOnly') is True:event['debugOnly']=True # on live-debug.html only (organisers' tests)
        out.append(event)
    return out

def convert(folder,conf,warnings=None):
    # conf: name/timezone/miniconf_url from config.yml (see build_miniconf.read_config).
    # warnings=None: any data problem aborts (manual upload). With a list, problems are
    # recorded there and the offending row/link is skipped, so CI builds never stop on sheet edits.
    def problem(message):
        if warnings is None:raise ValueError(message)
        warnings.append(message)
    sources={n:find_csv(folder,n) for n in ['events','papers','session_assignment']}
    events,papers,assign=(read(sources[n]) for n in ['events','papers','session_assignment'])
    paper_by_id={}
    for row in papers:
        uid=row.get('uid','').strip()
        if not re.fullmatch(r'\d+',uid) or uid in paper_by_id or not row.get('title','').strip():problem(f'papers.csv: missing/duplicate uid or title (uid={uid!r})');continue
        paper_by_id[uid]=row
    if not assign or 'Session Name' not in assign[0]:raise ValueError('session_assignment.csv 缺少 Session Name 列')
    columns={k:int(k[3:]) for k in assign[0] if re.fullmatch(r'PS-\d+',k)}
    if not columns or len(set(columns.values()))!=len(columns):raise ValueError('缺少或重复 PS-xx 列')
    groups={n:[] for n in columns.values()};used=set();positions=set();block_times={}
    for row in assign:
        label=row['Session Name'].strip();m=re.fullmatch(r'Paper-(\d+)',label,re.I)
        if label.startswith('Session Day & Time'):block_times={n:row[k].strip() for k,n in columns.items()}
        if not m:continue
        pos=int(m[1])
        if pos<1 or pos in positions:problem(f'session_assignment.csv: 重复或无效的 Paper-n 行 ({label})');continue
        positions.add(pos)
        for col,num in columns.items():
            uid=row[col].strip()
            if not uid:continue
            if uid not in paper_by_id:problem(f'{col}/{label}: 论文 uid {uid} 不存在');continue
            if uid in used:problem(f'{col}/{label}: 论文 uid {uid} 被分配多次');continue
            used.add(uid);groups[num].append((pos,uid))
    if used!=set(paper_by_id):problem('未分配的论文 uid: '+', '.join(sorted(set(paper_by_id)-used)))
    output=[];seen=set();ordinary={};notes=[]
    for idx,row in enumerate(events,1):
        uid=row.get('uid','').strip();title=helper.clean_text(row.get('title'))
        if not uid or uid in seen or not title:problem(f'events.csv: missing/duplicate uid or title (row {idx}, uid={uid!r})');continue
        seen.add(uid);category=helper.clean_text(row.get('category'))
        typ=helper.event_type(title,category)
        if category.lower()=='tutorials':typ='tutorial'
        if category.lower()=='special':typ='special'
        if category.lower()=='award nominee':typ='special'
        tbd=row.get('end_time','').strip().lower() in {'','tbd','tba'}
        try:
            start=helper.parse_local_datetime(row.get('start_date'),row.get('start_time'),conf['timezone'])
            if tbd:
                end=(start+timedelta(days=1)).replace(hour=0,minute=0,second=0)
                notes.append(f'{title}: 结束时间待定，显示 TBD；仅用当地次日零点作为列表归档界限。')
            else:
                end=helper.parse_local_datetime(row.get('start_date'),row.get('end_time'),conf['timezone'])
                if end<=start:end+=timedelta(days=1)
        except ValueError as error:
            problem(f'events.csv: {title} (uid {uid}) 时间无效: {error}');continue
        links={}
        for src,dst in [('web_link','info'),('channel_url','slack'),('thumbnail_link','thumbnail')]:
            if row.get(src,'').strip():links[dst]=row[src].strip()
        live=row.get('live_url','').strip()
        if live:links['zoom' if re.search(r'(^|\.)(zoom\.us|zoom\.com|zoomgov\.com)$',urlsplit(live).hostname or '') else 'youtube']=live
        event={'id':'event-'+uid,'sourceEventId':uid,'title':title,'type':typ,'category':category,'track':'poster' if typ=='poster' else 'main','startsAt':start.isoformat(),'endsAt':end.isoformat(),'links':links,'day':start.strftime('%A'),'dayNumber':helper.parse_int(row.get('day')),'topic':helper.topic_from_event(typ,category),'summary':helper.clean_text(row.get('description')),'organiser':helper.clean_text(row.get('organiser'))}
        page=event_link(row)
        if page:event['detailUrl']=f"{conf['miniconf_url']}/{page}"
        if tbd:event['endTimeTBD']=True
        if 'zoom' in links:event['zoomKind']='meeting' if typ=='poster' else 'webinar'
        match=re.fullmatch(r'(Poster|Oral)\s+Session\s*-?\s*(\d+)',title,re.I)
        if match:
            num=int(match[2]);key=(typ,num)
            if num not in groups or key in ordinary:
                problem(f'{title}: 缺少或重复分组')
                output.append(event);continue
            ordinary[key]=event;event['sessionNumber']=num
            if typ=='poster':event['posterSessionNumber']=num
            event['papers']=[]
            for pos,puid in sorted(groups[num]):
                raw=paper_by_id[puid]
                paper=helper.build_paper(raw,event['id'],num,pos)
                # Stable source identity, independent of positional changes; separate Oral display instances.
                paper['id']=f'paper-{puid}' if typ=='poster' else f'oral-{num}-paper-{puid}'
                paper['displayId']=f'P{num}-{pos:02d}'
                paper['detailUrl']=f"{conf['miniconf_url']}/poster_{puid}.html"
                # Unknown attendance mode must not silently become "onsite".
                if not raw.get('paper_presentation','').strip():paper.pop('presenterMode',None)
                fact=helper.clean_text(raw.get('fun_facts'))
                if fact:paper['funFact']=fact
                for source,destination in [('raw_pdf_path','pdf'),('raw_video','video'),('raw_poster_pdf','poster'),('raw_thumbnail','thumbnail'),('raw_slides_pdf','slides')]:
                    value=raw.get(source,'').strip()
                    if value and urlsplit(value).scheme=='https':paper.setdefault('links',{})[destination]=value
                event['papers'].append(paper)
            if groups[num]:event['paperRange']={'first':min(p for p,_ in groups[num]),'last':max(p for p,_ in groups[num])}
        output.append(event)
    for n in groups:
        if ('poster',n) not in ordinary or ('oral',n) not in ordinary:problem(f'PS-{n:02d}: 找不到对应 Oral 与 Poster 场次');continue
        oral,poster=ordinary['oral',n],ordinary['poster',n]
        expected=f"{datetime.fromisoformat(oral['startsAt']).strftime('%a, %H:%M')} - {datetime.fromisoformat(poster['endsAt']).strftime('%H:%M')}"
        if block_times.get(n) and re.sub(r'\s+',' ',block_times[n])!=expected:problem(f'PS-{n:02d}: 分组表时间 {block_times[n]} 与 events.csv 的 Oral+Poster 时间 {expected} 不一致')
    output.sort(key=lambda e:(e['startsAt'],e['id']))
    if not any(e['links'].get('zoom') for e in output):notes.append('CSV 中没有 Zoom 链接。测试时在后台的“测试会议链接”填写。')
    return {'schemaVersion':7,'generatedAt':datetime.now(timezone.utc).isoformat(),'conference':helper.infer_conference(events,conf),'events':output,'source':[p.name for p in sources.values()]},notes

# ---- Below: standalone CLI, not part of the miniconf build. Likely the backend maintainer's
# manual deploy tool (writes output/, edits the backend's wrangler.jsonc). Kept until the backend source is available.

def configure():
    path=ROOT/'site-config.json'
    if path.exists():return json.loads(path.read_text())
    backend=input('Cloudflare 后台网址（https://...workers.dev）：').strip().rstrip('/')
    username=input('GitHub 用户名：').strip()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?',username):raise ValueError('GitHub 用户名无效')
    url=urlsplit(backend)
    if url.scheme!='https' or not url.netloc or url.path or url.query or url.fragment or url.username:raise ValueError('请填写后台 HTTPS origin，不带路径')
    config={'backend':backend,'githubOrigin':'https://'+username.lower()+'.github.io'}
    path.write_text(json.dumps(config,indent=2)+'\n');return config

def unpinned_slack_items(schedule):
    # app_redirect without team= opens the channel in the viewer's last-used workspace.
    # https://<workspace>.slack.com/archives/<id> links already name the workspace.
    for item in [e for e in schedule['events']]+[p for e in schedule['events'] for p in e.get('papers',[])]:
        parts=urlsplit(item.get('links',{}).get('slack',''))
        if parts.hostname=='slack.com' and parts.path=='/app_redirect' and 'team=' not in parts.query:yield item

def pin_slack_team(schedule,team):
    if not team:return 0
    if not re.fullmatch(r'[TE][A-Z0-9]{6,}',team):raise ValueError('site-config.json slackTeamId 应为 T 开头的 Slack Team ID')
    changed=0
    for item in list(unpinned_slack_items(schedule)):
        item['links']['slack']+='&team='+team;changed+=1
    return changed

def main():
    folder=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'downloaded sitedata'
    schedule,notes=convert(folder)
    config=configure()
    pin_slack_team(schedule,config.get('slackTeamId','').strip())
    if any(unpinned_slack_items(schedule)):notes.append('site-config.json 未设置 slackTeamId：Slack 链接会在用户上次使用的工作区打开。')
    out=ROOT/'output';out.mkdir(exist_ok=True)
    # Build public files before replacing the ready-to-upload schedule.
    with tempfile.TemporaryDirectory() as temporary:
        stage=Path(temporary)/'schedule.json';stage.write_text(json.dumps(schedule,ensure_ascii=False,indent=2)+'\n')
        build(out/'github-pages',config['backend'],stage)
        temp=out/'schedule.json.tmp';temp.write_text(stage.read_text());os.replace(temp,out/'schedule.json')
    # Add the GitHub origin without dropping other allowed origins; leave the file untouched if already present.
    wrangler=ROOT/'wrangler.jsonc';settings=json.loads(wrangler.read_text(encoding='utf-8'))
    origins=[s.strip() for s in settings['vars'].get('PUBLIC_VIEW_ORIGINS','').split(',') if s.strip()]
    if config['githubOrigin'].lower() not in {o.lower() for o in origins}:
        settings['vars']['PUBLIC_VIEW_ORIGINS']=','.join(origins+[config['githubOrigin']]);wrangler.write_text(json.dumps(settings,indent=2)+'\n',encoding='utf-8')
    (out/'import-notes.txt').write_text('\n'.join(notes)+'\n')
    print(f"已生成 {len(schedule['events'])} 个活动、{sum(len(e.get('papers',[])) for e in schedule['events'] if e['type']=='poster')} 篇 Poster 论文。")
    print('1. 后台上传 output/schedule.json\n2. GitHub 仓库上传 output/github-pages 内的文件（不是外层文件夹）。')
    print('首次运行后执行 npm run deploy，让 GitHub 默认网址的跨域配置生效；以后只更新数据无需部署。')
    for note in notes:print(note)

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError) as error:print('未完成更新：'+str(error),file=sys.stderr);sys.exit(1)
