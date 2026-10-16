"""What the public Live Overview ships, shared by both builds (build_miniconf.py, build_public_site.py)."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / 'shared'   # used by the Warm-up Discussion (preconf/) too

# Page files, from overview-source/ unless listed in SHARED_FILES.
ASSETS = ('index.html', 'history.html', 'styles.css', 'llm-prompts.json',
          'site-integration.js', 'public-connection.js', 'prompt-config.js', 'overview-common.js',
          'app.js', 'history.js', 'cursor-avatars.js', 'egg-account.js',
          'site-chrome.js', 'timezone-preference.js', 'canon-egg.js')
SHARED_FILES = {'site-chrome.js', 'timezone-preference.js', 'canon-egg.js'}

# The offline fallback (schedule-snapshot.json) keeps schedule metadata only: no links, no live data.
EVENT_FIELDS = ('id', 'type', 'title', 'topic', 'summary', 'organiser', 'startsAt', 'endsAt', 'day',
                'dayNumber', 'track', 'category', 'spotlight', 'sessionNumber', 'posterSessionNumber', 'paperRange', 'endTimeTBD')
PAPER_FIELDS = ('id', 'displayId', 'sourcePaperId', 'detailUrl', 'title', 'authors', 'primaryAuthor', 'abstract', 'subjects', 'isTismir', 'longPresentation',
                'presenterMode', 'funFact', 'sessionId', 'sessionNumber', 'posterSessionNumber', 'sessionPaperNumber')
CONF_FIELDS = ('name', 'location', 'theme', 'timeZone', 'startsOn', 'endsOn', 'pageTitle', 'subtitle')


def asset_source(name):
    return (SHARED if name in SHARED_FILES else ROOT / 'overview-source') / name


def content_version(texts):
    """One version for a whole build: changes exactly when any shipped file changes (cache busting)."""
    digest = hashlib.sha256()
    for name in sorted(texts):
        digest.update(name.encode() + b'\0' + texts[name].encode('utf-8'))
    return digest.hexdigest()[:12]


def snapshot(schedule):
    now = datetime.now(timezone.utc).isoformat()

    def item(source, fields):
        result = {key: source[key] for key in fields if key in source}
        result['headcounts'] = {'zoom': 0, 'available': False, 'partial': False}
        result['metrics'] = {'available': False}
        result['links'] = {}
        return result

    events = []
    for e in schedule.get('events', []):
        if e.get('debugOnly'):
            continue
        result = item(e, EVENT_FIELDS)
        result['papers'] = [item(p, PAPER_FIELDS) for p in e.get('papers', [])]
        events.append(result)
    conference = schedule.get('conference', {})
    return {'schemaVersion': 3, 'version': 0, 'updatedAt': now, 'serverNow': now, 'offline': True,
            'conference': {k: conference.get(k) for k in CONF_FIELDS if k in conference},
            'debugClock': {'enabled': False, 'revision': 0}, 'events': events}
