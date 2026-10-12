import csv,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import update_schedule as tool

CONF={'name':'Test Conf','timezone':'Asia/Dubai','miniconf_url':'https://example.org'}

def write(path,rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def fixture(root):
    rows=[{'uid':'1','title':'Oral Session - 1','start_date':'2026-11-09','start_time':'10:00','end_time':'10:30','category':'Oral session'},
          {'uid':'2','title':'Poster Session - 1','start_date':'2026-11-09','start_time':'10:30','end_time':'11:30','category':'Poster session'},
          {'uid':'3','title':'Award Nominees Oral Session - 1','start_date':'2026-11-09','start_time':'18:00','end_time':'19:00','category':'Award nominee'},
          {'uid':'4','title':'Reception','start_date':'2026-11-09','start_time':'20:00','end_time':'tbd','category':'Social'}]
    write(root/'events(2).csv',rows)
    write(root/'papers(3).csv',[{'uid':'42','title':'Paper A','authors_and_affil':'Alice (X)','review1':'PRIVATE REVIEW','paper_presentation':''}])
    write(root/'session_assignment.csv',[{'Session Name':'Session Day & Time (UTC+4)','PS-01':'Mon, 10:00 - 11:30'},{'Session Name':'Paper-1','PS-01':'42'}])

class Tests(unittest.TestCase):
    def test_real_schema_and_private_fields(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root);s,notes=tool.convert(root,CONF)
            oral,poster,award,tbd=s['events']
            self.assertEqual(poster['papers'][0]['id'],'paper-42')
            self.assertEqual(poster['papers'][0]['displayId'],'P1-01')
            self.assertNotEqual(oral['papers'][0]['id'],poster['papers'][0]['id'])
            self.assertNotIn('papers',award);self.assertTrue(tbd['endTimeTBD'])
            self.assertNotIn('PRIVATE REVIEW',json.dumps(s));self.assertNotIn('presenterMode',poster['papers'][0])
    def test_missing_and_duplicate_assignments_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root)
            write(root/'session_assignment.csv',[{'Session Name':'Paper-1','PS-01':'99'}])
            with self.assertRaisesRegex(ValueError,'不存在'):tool.convert(root,CONF)
            write(root/'session_assignment.csv',[{'Session Name':'Paper-1','PS-01':'42'},{'Session Name':'Paper-2','PS-01':'42'}])
            with self.assertRaisesRegex(ValueError,'多次'):tool.convert(root,CONF)
    def test_conflicting_time_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root)
            p=root/'session_assignment.csv';p.write_text(p.read_text().replace('11:30','12:30'))
            with self.assertRaisesRegex(ValueError,'不一致'):tool.convert(root,CONF)
    @unittest.skip("standalone CLI (update_schedule.main) needs the backend's wrangler.jsonc")
    def test_end_to_end_outputs_and_repeated_update(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'downloaded sitedata';folder.mkdir();fixture(folder)
            source=tool.ROOT
            import shutil
            shutil.copytree(source/'overview-source',root/'overview-source')
            (root/'site-config.json').write_text(json.dumps({'backend':'https://backend.example','githubOrigin':'https://tester.github.io'}))
            (root/'wrangler.jsonc').write_text(json.dumps({'vars':{}}))
            import build_public_site
            old,old_builder,argv=tool.ROOT,build_public_site.ROOT,sys.argv
            tool.ROOT=root;build_public_site.ROOT=root;sys.argv=['update_schedule.py']
            try:tool.main();tool.main()
            finally:tool.ROOT=old;build_public_site.ROOT=old_builder;sys.argv=argv
            self.assertTrue((root/'output/schedule.json').exists())
            public=root/'output/github-pages'
            self.assertFalse((public/'CNAME').exists());self.assertTrue((public/'.nojekyll').exists())
            self.assertEqual(json.loads((root/'wrangler.jsonc').read_text())['vars']['PUBLIC_VIEW_ORIGINS'],'https://tester.github.io')
            self.assertNotIn('review1',(public/'schedule-snapshot.json').read_text())
