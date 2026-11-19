"""V5 pilot: HMRC OData -> Supabase REST. Never print credentials."""
import argparse, os, re, time, logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
import requests

API='https://api.uktradeinfo.com/'
LOG=logging.getLogger('collector')
S=requests.Session()

def hmrc(endpoint, filt, max_records=250000):
    url=urljoin(API,endpoint); params={'$filter':filt,'$top':1000}
    output=[];seen=set()
    while url:
        if url in seen:raise RuntimeError('HMRC pagination loop')
        seen.add(url)
        if len(output)>=max_records:raise RuntimeError('HMRC record safety ceiling reached; incomplete retrieval')
        for attempt in range(6):
            try:
                r=S.get(url,params=params,timeout=65,headers={'Accept':'application/json'})
                if r.status_code in (429,500,502,503,504):
                    if attempt==5:r.raise_for_status()
                    time.sleep(min(45,2**attempt));continue
                r.raise_for_status();break
            except requests.RequestException:
                if attempt==5:raise
                time.sleep(min(45,2**attempt))
        payload=r.json();items=payload.get('value')
        if not isinstance(items,list):raise RuntimeError('Unexpected HMRC response structure')
        output.extend(items)
        nxt=payload.get('@odata.nextLink')
        if nxt:
            url=urljoin(API,nxt)
            if urlparse(url).netloc!='api.uktradeinfo.com':raise RuntimeError('Unsafe HMRC nextLink')
        else:url=None
        params=None
        if not items and url:raise RuntimeError('HMRC returned empty page with continuation')
    return output

def norm(item):return {str(k).lower():v for k,v in item.items()}
def trader(t):
    x=norm(t); tid=str(x.get('traderid','')).strip()
    if not tid.isdigit():return None
    address=', '.join(str(v) for k,v in t.items() if 'address' in str(k).lower() and v)
    return {'trader_id':int(tid),'company_name':str(x.get('companyname') or x.get('tradername') or x.get('name') or ''), 'postcode':str(x.get('postcode') or ''),'registered_address':address,'updated_at':datetime.now(timezone.utc).isoformat()}
def esc(s):return s.replace("'","''")
def parse_ym(v):
    try:
        n=int(v);y,m=divmod(n,100)
        if 2000<=y<=2100 and 1<=m<=12:return f'{y:04d}-{m:02d}-01'
    except (TypeError,ValueError):pass
    return None

class DB:
    def __init__(self):
        url=os.environ['SUPABASE_URL'].rstrip('/')
        key=os.environ['SUPABASE_SECRET_KEY']
        if not url.startswith('https://') or not url.endswith('.supabase.co'):raise RuntimeError('Invalid SUPABASE_URL')
        self.url=url+'/rest/v1/'
        self.headers={'apikey':key,'Content-Type':'application/json','Prefer':'resolution=merge-duplicates,return=minimal'}
    def write(self,table,rows,conflict=None):
        if not rows:return
        for i in range(0,len(rows),300):
            params={'on_conflict':conflict} if conflict else None
            r=S.post(self.url+table,headers=self.headers,params=params,json=rows[i:i+300],timeout=65)
            if not r.ok:raise RuntimeError(f'Supabase {table} write failed HTTP {r.status_code}: {r.text[:450]}')
    def get(self,table,params):
        r=S.get(self.url+table,headers=self.headers,params=params,timeout=65)
        r.raise_for_status();return r.json()
    def job(self,territory):
        r=S.post(self.url+'collection_jobs',headers={**self.headers,'Prefer':'return=representation'},json={'territory':territory,'status':'running'},timeout=40)
        r.raise_for_status();return r.json()[0]['id']
    def update_job(self,jid,**data):
        r=S.patch(self.url+'collection_jobs',headers=self.headers,params={'id':f'eq.{jid}'},json=data,timeout=40)
        r.raise_for_status()

def activity(db,t,start,end):
    tid=t['trader_id']; rows=[]
    for endpoint,direction in [('Import','Import'),('Export','Export')]:
        items=hmrc(endpoint,f'TraderId eq {tid} and MonthId ge {start} and MonthId le {end}')
        for raw in items:
            x=norm(raw)
            if str(x.get('traderid'))!=str(tid):raise RuntimeError('TraderId mismatch in HMRC activity')
            month=parse_ym(x.get('monthid'));code=str(x.get('commodityid') or '').strip()
            if not month or not code:raise RuntimeError('Invalid MonthId or CommodityId')
            rows.append({'trader_id':tid,'direction':direction,'trade_month':month,'commodity_code':code,'commodity_description':None})
    # De-duplicate before writing; HMRC records are commodity-month evidence, not shipments.
    rows=list({(r['trader_id'],r['direction'],r['trade_month'],r['commodity_code']):r for r in rows}.values())
    db.write('trade_records',rows,'trader_id,direction,trade_month,commodity_code')
    stamp=datetime.now(timezone.utc).isoformat()
    db.write('trader_verification',[{'trader_id':tid,'import_status':'complete','export_status':'complete','last_verified_at':stamp,'error_message':None}],'trader_id')
    return len(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['pilot','postcode'],default='pilot');p.add_argument('--postcode',default='M1');p.add_argument('--start',type=int,default=202410);p.add_argument('--end',type=int,default=202609);p.add_argument('--batch',type=int,default=60);p.add_argument('--names',default='Funko UK;All About Food Limited');a=p.parse_args()
    if not parse_ym(a.start) or not parse_ym(a.end) or a.start>a.end:raise ValueError('Invalid reporting window')
    db=DB(); territory='pilot known traders' if a.mode=='pilot' else a.postcode.strip().upper()
    jid=db.job(territory);failed=0;verified=0;discovered=0
    try:
        found=[]
        if a.mode=='pilot':
            for name in a.names.split(';'):
                if name.strip():found+=hmrc('Trader',f"contains(tolower(CompanyName),'{esc(name.strip().lower())}')")
        else:
            code=a.postcode.strip().upper().replace(' ','')
            if not re.fullmatch(r'[A-Z]{1,2}\d{1,2}[A-Z]?',code):raise ValueError('Use a district such as M1 or CV3')
            # Do not claim full coverage until HMRC postcode filter is validated.
            found=hmrc('Trader',f"startswith(PostCode,'{code}')")
            LOG.warning('Postcode API matching must be reconciled against HMRC directory before declaring complete coverage')
        candidates={t['trader_id']:t for x in found if (t:=trader(x))}
        if a.mode=='postcode':
            candidates={k:v for k,v in candidates.items() if re.sub(r'\s+','',v['postcode'].upper()).startswith(code)}
        discovered=len(candidates)
        LOG.info('Directory records: %s; distinct IDs: %s',len(found),discovered)
        db.write('traders',list(candidates.values()),'trader_id')
        # Only process a bounded batch per Actions run, resuming from completed verification.
        ids=list(candidates)
        already=set()
        for i in range(0,len(ids),100):
            subset=ids[i:i+100]
            if not subset:continue
            # PostgREST in filter uses numeric list; only completed checks are skipped.
            records=db.get('trader_verification',{'select':'trader_id,import_status,export_status','trader_id':'in.('+','.join(map(str,subset))+')'})
            already|={int(x['trader_id']) for x in records if x.get('import_status')=='complete' and x.get('export_status')=='complete'}
        todo=[v for k,v in candidates.items() if k not in already][:max(1,a.batch)]
        LOG.info('Already verified %s; checking %s in this run',len(already),len(todo))
        for t in todo:
            try:
                n=activity(db,t,a.start,a.end);verified+=1
                LOG.info('Trader %s: %s commodity-month records',t['trader_id'],n)
            except Exception as e:
                failed+=1;LOG.error('Trader %s failed: %s',t['trader_id'],str(e)[:200])
                # Never mark a partial import/export as complete.
                db.write('trader_verification',[{'trader_id':t['trader_id'],'import_status':'failed','export_status':'failed','error_message':str(e)[:300]}],'trader_id')
        remaining=max(0,discovered-len(already)-verified)
        status='partial' if remaining or failed else 'complete'
        db.update_job(jid,status=status,traders_discovered=discovered,traders_verified=verified,traders_failed=failed,completed_at=datetime.now(timezone.utc).isoformat())
        LOG.info('Job %s: %s, discovered=%s, checked_this_run=%s, failed=%s, remaining=%s',jid,status,discovered,verified,failed,remaining)
        if failed:raise RuntimeError(f'{failed} trader checks failed; inspect Actions logs')
    except Exception:
        db.update_job(jid,status='failed',traders_discovered=discovered,traders_verified=verified,traders_failed=failed,completed_at=datetime.now(timezone.utc).isoformat())
        raise

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s');main()
