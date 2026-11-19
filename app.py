"""UK Freight Sales Intelligence V4.6 — one trader-ID evidence path for every search mode."""
import concurrent.futures
import math
import re
import time
from datetime import date
from urllib.parse import urljoin
import pandas as pd
import requests
import streamlit as st

BASE='https://api.uktradeinfo.com/'
st.set_page_config(page_title='UK Freight Sales Intelligence',page_icon='🚢',layout='wide',initial_sidebar_state='collapsed')
st.markdown('''<style>.block-container{max-width:1150px;padding-top:1.1rem}[data-testid="stMetric"]{background:#142d3a!important;border:1px solid #426575;padding:12px;border-radius:12px}[data-testid="stMetric"] label,[data-testid="stMetric"] p,[data-testid="stMetricValue"]{color:#fff!important;opacity:1!important}[data-testid="stMetricValue"]{font-weight:800!important}@media(max-width:650px){.block-container{padding:1rem .75rem 3rem}.stButton button{min-height:46px}}</style>''',unsafe_allow_html=True)
st.title('🚢 UK Freight Sales Intelligence · V4.6')
st.caption('HMRC published trade evidence • consistent Trader ID matching • sales-first shortlist')

def clean(v):return re.sub(r'\s+','',str(v or '').upper())
def outcode(v):
    # UK full postcodes end in the three-character inward code (e.g. CV34PB -> CV3).
    raw=clean(v)
    return raw[:-3] if re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}',raw) else ''
def month_idx(v):
    y,m=divmod(int(v),100)
    return y*12+m-1
def ym(i):return (i//12)*100+i%12+1
def valid_ym(v):
    try:
        y,m=divmod(int(v),100)
        return 2000<=y<=2100 and 1<=m<=12
    except (ValueError,TypeError):return False
def month_name(v):return f'{int(v)//100:04d}-{int(v)%100:02d}' if v is not None else 'Not observed'
def row(t):
    x={str(k).lower():v for k,v in t.items()}
    return {'Trader ID':str(x.get('traderid','')).strip(),'Company':str(x.get('tradername') or x.get('companyname') or x.get('name') or ''),'Postcode':str(x.get('postcode') or ''),'Registered address':', '.join(str(v) for k,v in t.items() if 'address' in str(k).lower() and v)}

def api_get(url,params=None):
    for attempt in range(4):
        try:
            r=requests.get(url,params=params,headers={'Accept':'application/json'},timeout=40)
            if r.status_code in (429,500,502,503,504) and attempt<3:
                time.sleep(1.5*(attempt+1));continue
            r.raise_for_status()
            obj=r.json()
            if not isinstance(obj,dict) or not isinstance(obj.get('value'),list):raise ValueError('Unexpected HMRC response shape')
            return obj
        except requests.RequestException:
            if attempt==3:raise
            time.sleep(1.5*(attempt+1))

def paged(endpoint,filter_text,select=None,max_rows=10000):
    url=urljoin(BASE,endpoint)
    params={'$filter':filter_text,'$top':min(2000,max_rows)}
    if select:params['$select']=select
    result=[];pages=0;seen=set()
    while url and len(result)<max_rows:
        if url in seen:raise ValueError('Repeated HMRC pagination URL')
        seen.add(url)
        payload=api_get(url,params)
        chunk=payload['value'];pages+=1
        result.extend(chunk[:max_rows-len(result)])
        nxt=payload.get('@odata.nextLink')
        url=urljoin(BASE,nxt) if nxt else None
        if url and not url.startswith(BASE):raise ValueError('Unsafe pagination URL')
        params=None
        if not chunk:break
    return result,bool(url),pages

@st.cache_data(ttl=3600,show_spinner=False)
def traders_by_name(name,max_rows):
    escaped=name.lower().replace("'","''")
    return paged('Trader',f"contains(tolower(CompanyName),'{escaped}')",max_rows=max_rows)

@st.cache_data(ttl=3600,show_spinner=False)
def traders_by_prefix(prefix,max_rows):
    # HMRC postcode filters have proved inconsistent for some districts. Try direct,
    # then a broader-area scan; never claim that a capped fallback is exhaustive.
    found,cap,pages=paged('Trader',f"startswith(PostCode,'{prefix}')",max_rows=max_rows)
    if found or not re.search(r'\d',prefix):return found,cap,pages,'direct'
    area=re.match(r'^[A-Z]{1,2}',prefix).group()
    broader,bcap,bpages=paged('Trader',f"startswith(PostCode,'{area}')",max_rows=max(max_rows,15000))
    exact=[t for t in broader if outcode(t.get('PostCode',''))==prefix]
    return exact,bcap,bpages,'area fallback'+(' (incomplete)' if bcap else '')

@st.cache_data(ttl=3600,show_spinner=False)
def trader_activity(tid,flow,start,end,max_rows):
    if not re.fullmatch(r'\d+',str(tid)):raise ValueError(f'Unexpected Trader ID {tid!r}')
    return paged(flow,f'TraderId eq {tid} and MonthId ge {start} and MonthId le {end}',
                 select='TraderId,MonthId,CommodityId',max_rows=max_rows)

@st.cache_data(ttl=86400,show_spinner=False)
def location_for_postcodes(postcodes):
    result={}
    for i in range(0,len(postcodes),100):
        batch=list(postcodes[i:i+100])
        r=requests.post('https://api.postcodes.io/postcodes',json={'postcodes':batch},timeout=30)
        r.raise_for_status()
        for item in r.json().get('result',[]):
            p=item.get('result')
            if p and p.get('latitude') is not None:result[clean(item['query'])]=(p['latitude'],p['longitude'])
    return result

def miles(a,b):
    x,y=map(math.radians,a);p,q=map(math.radians,b)
    z=math.sin((p-x)/2)**2+math.cos(x)*math.cos(p)*math.sin((q-y)/2)**2
    return 3958.7613*2*math.asin(min(1,math.sqrt(z)))

@st.cache_data(ttl=86400,show_spinner=False)
def radius_outcodes(postcode,radius):
    p=requests.get('https://api.postcodes.io/postcodes/'+clean(postcode),timeout=25)
    p.raise_for_status();origin=p.json().get('result')
    if not origin:raise ValueError('Full postcode not found')
    requested=int(radius*1609.344+5000);actual=min(requested,24999)
    r=requests.get('https://api.postcodes.io/outcodes',params={'lon':origin['longitude'],'lat':origin['latitude'],'radius':actual,'limit':100},timeout=30)
    r.raise_for_status();items=r.json().get('result') or []
    codes=sorted({clean(x.get('outcode')) for x in items if x.get('outcode')}|{outcode(postcode)})
    return codes,len(items)>=100,actual<requested

def evidence_for_trader(tid,start,end,max_rows):
    im,ic,ip=trader_activity(tid,'Import',start,end,max_rows)
    ex,ec,ep=trader_activity(tid,'Export',start,end,max_rows)
    # Do not silently score a partially retrieved trader.
    return str(tid),im,ex,ic or ec,ip+ep

def evidence_months(records,tid):
    out=[];bad=0
    for x in records:
        low={str(k).lower():v for k,v in x.items()}
        if str(low.get('traderid',''))!=str(tid) or not valid_ym(low.get('monthid')):
            bad+=1;continue
        out.append((int(low['monthid']),str(low.get('commodityid') or '')))
    return out,bad

def score(trader,im,ex,anchor):
    tid=trader['Trader ID'];im,bad1=evidence_months(im,tid);ex,bad2=evidence_months(ex,tid)
    if bad1+bad2:raise ValueError(f'{bad1+bad2} activity records have invalid trader IDs or months for {tid}')
    a=month_idx(anchor);win12={ym(i) for i in range(a-11,a+1)};win24={ym(i) for i in range(a-23,a+1)}
    previous={ym(i) for i in range(a-23,a-11)}
    result=dict(trader)
    for flow,records in [('Import',im),('Export',ex)]:
        for n,window in [(12,win12),(24,win24)]:
            result[f'{flow} active months ({n}m)']=len({m for m,c in records if m in window})
            result[f'{flow} published lines ({n}m)']=sum(m in window for m,c in records)
        result[f'{flow} previous 12m active months']=len({m for m,c in records if m in previous})
        result[f'{flow} commodity codes (24m)']=', '.join(sorted({c for m,c in records if m in win24 and c}))
        seen=[m for m,c in records if m in win24]
        result[f'Latest {flow.lower()}']=month_name(max(seen)) if seen else 'Not observed'
        result[f'{flow} last activity lag (months)']=a-month_idx(max(seen)) if seen else None
        for yr in sorted({ym(i)//100 for i in range(a-23,a+1)}):
            result[f'{flow} active months {yr}']=len({m for m,c in records if m//100==yr and m in win24})
    i=result['Import active months (12m)'];e=result['Export active months (12m)']
    i24=result['Import active months (24m)'];e24=result['Export active months (24m)']
    result['Trade direction']='Both' if i and e else 'Importer' if i else 'Exporter' if e else 'Historical activity' if i24 or e24 else 'No published activity observed'
    peak=max(i,e)
    result['Tier']='A' if peak>=10 else 'B' if peak>=4 else 'C' if peak>=1 else 'Historical' if i24 or e24 else 'Unverified'
    lag=min([v for v in [result['Import last activity lag (months)'],result['Export last activity lag (months)']] if v is not None],default=999)
    result['Sales priority']='High' if result['Tier']=='A' and lag<=3 else 'Medium' if result['Tier'] in ('A','B') and lag<=6 else 'Low' if i24 or e24 else 'Research'
    current=max(i,e);prior=max(result['Import previous 12m active months'],result['Export previous 12m active months'])
    result['Trend']='Growing' if current>prior+2 else 'Declining' if prior>current+2 else 'Stable / mixed'
    hs={'22':'Beverages — review specific products','27':'Fuels — specialist review','30':'Pharmaceuticals — specialist review','39':'Plastics','40':'Rubber','48':'Paper / packaging','61':'Knitted apparel','62':'Woven apparel','72':'Iron / steel','73':'Steel articles','84':'Machinery','85':'Electrical equipment','87':'Vehicles / parts','90':'Precision instruments'}
    codes={c for m,c in im+ex if m in win24 and c}
    result['Commodity groups (indicative)']=', '.join(sorted({hs.get(c[:2],'HS'+c[:2]) for c in codes})) or 'Not classified'
    result['HMRC trader profile']='https://www.uktradeinfo.com/traders/'+re.sub(r'[^a-z0-9]+','-',trader['Company'].lower()).strip('-')+'-'+tid
    result['Evidence status']='Verified: matched published commodity-month records' if i24 or e24 else 'No matched published activity in 24m'
    result['Data window end']=month_name(anchor)
    result['Sales rationale']=f"{result['Trade direction']}; {i}/12 import months, {e}/12 export months; last observed import {result['Latest import']}, export {result['Latest export']}. Verify freight fit, decision maker and CRM ownership."
    result['CRM status']='Not checked';result['Operating site']='Not verified'
    result['Shipment count']='Not available from this dataset'
    return result

mode=st.segmented_control('Search type',['Company name','Postcode area','Radius'],default='Postcode area')
if mode=='Company name':q=st.text_input('HMRC trader / company name',placeholder='Eden Horticulture Limited')
elif mode=='Postcode area':q=st.text_input('Postcode area or district',value='WS10')
else:
    q=st.text_input('Full postcode',value='CV3 4PB')
    radius=st.slider('Distance in miles',1,15,5)
verified=st.checkbox('Show only traders with matched published activity',value=True)
with st.expander('Advanced settings — retrieval and reporting'):
    anchor=st.text_input('Reporting window end (YYYYMM)',value='202609',help='Use the SAME month for every search. Change only after confirming HMRC has published newer data.')
    candidate_limit=st.select_slider('Maximum directory candidates to discover',options=[100,250,500,1000,2000,5000],value=1000)
    verify_limit=st.select_slider('Maximum traders to verify individually',options=[20,50,100,200,400],value=100)
    per_trader_limit=st.select_slider('Maximum records per trader per direction',options=[2000,5000,10000,30000],value=10000)
    workers=st.slider('Concurrent trader checks',1,6,4)
    st.caption('Company and postcode searches use the SAME Trader ID activity method. Large searches may take minutes. Reaching a candidate or verification cap means results are not exhaustive.')

if st.button('🔎 Search HMRC traders',type='primary',use_container_width=True):
    st.session_state.pop('report',None)
    try:
        code=clean(q)
        if not valid_ym(anchor):raise ValueError('Reporting window must be YYYYMM, for example 202609')
        anchor=int(anchor);start=ym(month_idx(anchor)-23)
        if mode=='Company name' and len(q.strip())<3:raise ValueError('Enter at least three characters')
        if mode=='Postcode area' and not re.fullmatch(r'[A-Z]{1,2}(?:\d{1,2}[A-Z]?)?',code):raise ValueError('Enter a postcode area or district such as TF or TF2')
        if mode=='Radius' and not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}',code):raise ValueError('Enter a full postcode such as CV3 4PB')
        notes=[];partial=False;discovery=[];source=[]
        with st.spinner('Discovering traders…'):
            if mode=='Company name':
                discovery,cap,pages=traders_by_name(q.strip(),candidate_limit)
                source=[f'Name: {q.strip()} ({pages} pages)'];partial|=cap
            elif mode=='Postcode area':
                discovery,cap,pages,method=traders_by_prefix(code,candidate_limit)
                source=[f'{code}: {method} ({pages} pages)'];partial|=cap
            else:
                districts,geo_cap,geo_short=radius_outcodes(code,radius)
                if geo_cap or geo_short:partial=True;notes.append('Geographic district discovery was limited; radius coverage is incomplete.')
                if len(districts)>35:partial=True;notes.append(f'Only 35 of {len(districts)} districts scanned.');districts=districts[:35]
                for d in districts:
                    batch,cap,pages,method=traders_by_prefix(d,candidate_limit)
                    discovery.extend(batch);source.append(f'{d}: {method} ({pages} pages)')
                    partial|=cap
        candidates=pd.DataFrame([row(t) for t in discovery],columns=['Trader ID','Company','Postcode','Registered address'])
        candidates=candidates[candidates['Trader ID'].str.fullmatch(r'\d+',na=False)].drop_duplicates('Trader ID')
        if mode=='Postcode area':
            candidates=candidates[candidates['Postcode'].map(clean).str.startswith(code)].copy()
            if re.search(r'\d',code):candidates=candidates[candidates['Postcode'].map(outcode)==code].copy()
        if mode=='Radius' and not candidates.empty:
            codes=tuple(sorted({code}|set(candidates['Postcode'].map(clean))))
            coords=location_for_postcodes(codes)
            if code not in coords:raise ValueError('Unable to geocode search postcode')
            candidates['Miles away']=candidates['Postcode'].map(lambda p:round(miles(coords[code],coords[clean(p)]),2) if clean(p) in coords else float('nan'))
            missing=int(candidates['Miles away'].isna().sum())
            if missing:notes.append(f'{missing} traders excluded because postcode geocoding was unavailable.')
            candidates=candidates[candidates['Miles away']<=radius].copy()
        # No arbitrary A/B/C score is inferred for companies not individually checked.
        discovered=len(candidates)
        if discovered>verify_limit:
            partial=True;notes.append(f'Only {verify_limit} of {discovered} discovered traders individually checked. Increase the verification limit or narrow the search.')
        selected=candidates.head(verify_limit).to_dict('records')
        records=[];errors=[];no_evidence=0;total_pages=0
        progress=st.progress(0,text='Verifying individual Trader IDs…')
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            tasks={pool.submit(evidence_for_trader,r['Trader ID'],start,anchor,per_trader_limit):r for r in selected}
            for n,fut in enumerate(concurrent.futures.as_completed(tasks),1):
                r=tasks[fut]
                try:
                    tid,im,ex,cap,pages=fut.result();total_pages+=pages
                    if cap:
                        errors.append(f"{r['Company']} ({tid}): evidence cap reached; not scored")
                    else:
                        scored=score(r,im,ex,anchor)
                        if scored['Tier']=='Unverified':no_evidence+=1
                        records.append(scored)
                except Exception as exc:errors.append(f"{r['Company']} ({r['Trader ID']}): {exc}")
                progress.progress(n/max(1,len(tasks)),text=f'Checked {n}/{len(tasks)} traders')
        progress.empty()
        if errors:partial=True;notes.append(f'{len(errors)} trader evidence checks failed or were capped. Their activity has NOT been scored as zero.')
        result=pd.DataFrame(records)
        st.session_state['report']={'data':result,'notes':notes,'partial':partial,'discovered':discovered,'checked':len(selected),'no_evidence':no_evidence,'errors':errors,'sources':source,'pages':total_pages,'mode':mode,'anchor':anchor,'verified_default':verified}
    except Exception as exc:st.error(f'Search failed: {exc}');st.info('An API error or incomplete search does not mean a trader has no trade activity.')

if 'report' in st.session_state:
    report=st.session_state['report'];df=report['data'].copy()
    if not df.empty and verified:df=df[df['Tier']!='Unverified'].copy()
    if not df.empty:
        with st.expander('Sales filters'):
            priorities=st.multiselect('Sales priority',['High','Medium','Low','Research'],default=['High','Medium','Low','Research'])
            directions=st.multiselect('Trade direction',['Both','Importer','Exporter','Historical activity','No published activity observed'],default=['Both','Importer','Exporter','Historical activity','No published activity observed'])
            minimum=st.slider('Minimum active months in either direction (12m)',0,12,0)
        df=df[df['Sales priority'].isin(priorities)&df['Trade direction'].isin(directions)]
        df=df[df[['Import active months (12m)','Export active months (12m)']].max(axis=1)>=minimum]
        ranks={'High':0,'Medium':1,'Low':2,'Research':3}
        df=df.assign(_sort=df['Sales priority'].map(ranks)).sort_values(['_sort','Import active months (12m)','Export active months (12m)'],ascending=[True,False,False]).drop(columns='_sort')
    for note in report['notes']:st.warning(note)
    if report['partial']:st.error('PARTIAL COVERAGE — do not interpret this list as every active trader in the territory.')
    st.info(f"All trader activity is evaluated against the SAME fixed 24-month window ending {month_name(report['anchor'])}. Each trader is matched by its own HMRC Trader ID. These are commodity-month records, NOT shipments.")
    a,b,c=st.columns(3);a.metric('Verified prospects',len(df));b.metric('A-tier',int((df['Tier']=='A').sum()) if 'Tier' in df else 0);c.metric('High priority',int((df['Sales priority']=='High').sum()) if 'Sales priority' in df else 0)
    st.caption(f"Directory candidates in territory: {report['discovered']:,} · Trader IDs individually checked: {report['checked']:,} · Complete checks with no activity: {report['no_evidence']:,} · Failed/capped checks: {len(report['errors']):,}")
    with st.expander('Retrieval diagnostics and exceptions'):
        st.write('Search mode:',report['mode']);st.write('Trader activity pages fetched:',report['pages'])
        st.write('Directory queries:',report['sources'])
        if report['errors']:st.code('\n'.join(report['errors'][:100]))
    if df.empty:st.warning('No verified traders displayed. This may be due to limited candidate coverage, failed checks, reporting-window settings, or genuinely absent published records.')
    else:
        cols=['Company','Postcode','Trade direction','Tier','Sales priority','Import active months (12m)','Export active months (12m)','Import active months (24m)','Export active months (24m)','Latest import','Latest export','Trend','Commodity groups (indicative)','HMRC trader profile','Evidence status','Sales rationale']
        st.subheader('Verified sales prospects')
        st.dataframe(df[[c for c in cols if c in df]],hide_index=True,use_container_width=True)
        st.download_button('⬇️ Sales-ready CSV',df[[c for c in cols if c in df]+['Trader ID']].to_csv(index=False).encode('utf-8-sig'),'hmrc_sales_ready_v4_6.csv','text/csv',use_container_width=True)
        st.download_button('⬇️ Full evidence CSV',df.to_csv(index=False).encode('utf-8-sig'),'hmrc_full_evidence_v4_6.csv','text/csv',use_container_width=True)
        with st.expander('Full evidence and calendar-year activity'):
            st.dataframe(df,hide_index=True,use_container_width=True)
    st.caption('Note: Calendar-year counts are limited to the selected 24-month window; they are not necessarily full-year totals. Registered addresses may differ from operating sites.')
