import math
import re
import time
from datetime import date
from urllib.parse import urljoin
import pandas as pd
import requests
import streamlit as st

BASE = 'https://api.uktradeinfo.com/'
st.set_page_config(page_title='UK Trader Finder', page_icon='🚢', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {padding-top:1.25rem;max-width:1100px}
[data-testid="stMetric"] {background:#f2f6f4;padding:14px;border-radius:12px}
@media(max-width:650px){.block-container{padding:1rem .8rem 3rem}.stButton button{min-height:48px}div[data-testid="stHorizontalBlock"]{gap:.4rem}}
</style>''',unsafe_allow_html=True)
st.title('🚢 UK Freight Sales Intelligence · V4')
st.caption('HMRC trade evidence → prioritised UK freight prospects')

@st.cache_data(ttl=3600,show_spinner=False)
def fetch_traders(prefix, cap):
    # Endpoint/field names based on published HMRC UK Trade Info OData conventions.
    url=urljoin(BASE,'Trader')
    params={'$filter':f"startswith(PostCode,'{prefix}')",'$top':min(500,cap)}
    rows=[]
    with requests.Session() as session:
        while url and len(rows)<cap:
            response=None
            for attempt in range(4):
                try:
                    response=session.get(url,params=params,timeout=40,headers={'Accept':'application/json'})
                    if response.status_code in (429,500,502,503,504) and attempt<3:
                        time.sleep(2**attempt)
                        continue
                    response.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt==3:raise
                    time.sleep(2**attempt)
            payload=response.json()
            chunk=payload.get('value',[])
            if not isinstance(chunk,list):raise ValueError('Unexpected HMRC response')
            rows.extend(chunk[:cap-len(rows)])
            nxt=payload.get('@odata.nextLink')
            url=urljoin(BASE,nxt) if nxt else None
            if url and not url.startswith(BASE):raise ValueError('Unexpected HMRC pagination URL')
            params=None
            if not chunk:break
    return rows, bool(url)

@st.cache_data(ttl=86400,show_spinner=False)
def lookup_postcodes(codes):
    found={}
    with requests.Session() as session:
        for i in range(0,len(codes),100):
            batch=codes[i:i+100]
            try:
                r=session.post('https://api.postcodes.io/postcodes',json={'postcodes':batch},timeout=25)
                r.raise_for_status()
                for item in r.json().get('result',[]):
                    v=item.get('result')
                    if v and v.get('latitude') is not None:
                        found[clean(item['query'])]=(v['latitude'],v['longitude'])
            except requests.RequestException:pass
    return found

def clean(s):return re.sub(r'\s+','',str(s or '').upper())
def distance(a,b):
    x,y=map(math.radians,a);p,q=map(math.radians,b)
    h=math.sin((p-x)/2)**2+math.cos(x)*math.cos(p)*math.sin((q-y)/2)**2
    return 3958.7613*2*math.asin(min(1,math.sqrt(h)))

def row_to_record(t):
    low={str(k).lower():v for k,v in t.items()}
    return {'Trader ID':low.get('traderid',''),'Company':low.get('tradername',low.get('name',low.get('companyname',''))),
            'Postcode':low.get('postcode',''),'Registered address':', '.join(str(v) for k,v in t.items() if 'address' in k.lower() and v)}

def ym_from_index(index):
    return (index // 12) * 100 + index % 12 + 1

def month_index(value):
    value=int(value)
    return (value // 100) * 12 + value % 100 - 1

def query_window():
    now=date.today()
    last_complete=now.year*12+now.month-2
    # 30 months: allow for delayed publication, while still analysing 24 published months.
    return ym_from_index(last_complete-29), ym_from_index(last_complete)

@st.cache_data(ttl=3600,show_spinner=False)
def fetch_activity(prefix,flow,start,end,cap=30000):
    # Query published commodity-month records, not individual shipment declarations.
    url=urljoin(BASE,flow)
    params={'$filter':f"MonthId ge {start} and MonthId le {end} and startswith(Trader/PostCode,'{prefix}')",
            '$select':'TraderId,MonthId,CommodityId','$top':min(2000,cap)}
    records=[]
    with requests.Session() as session:
        while url and len(records)<cap:
            for attempt in range(4):
                try:
                    r=session.get(url,params=params,timeout=50,headers={'Accept':'application/json'})
                    if r.status_code in (429,500,502,503,504) and attempt<3:
                        time.sleep(2**attempt+1);continue
                    r.raise_for_status();break
                except requests.RequestException:
                    if attempt==3:raise
                    time.sleep(2**attempt+1)
            payload=r.json()
            chunk=payload.get('value',[])
            if not isinstance(chunk,list):raise ValueError('Unexpected activity response')
            records.extend(chunk[:cap-len(records)])
            next_url=payload.get('@odata.nextLink')
            url=urljoin(BASE,next_url) if next_url else None
            if url and not url.startswith(BASE):raise ValueError('Unexpected pagination URL')
            params=None
            if not chunk:break
    return records,bool(url)

def month_label(value):
    if value is None or pd.isna(value):
        return 'Not observed'
    value=int(value)
    return f'{value//100:04d}-{value%100:02d}'

def valid_month(value):
    try:
        x=int(value)
        return 1 <= x%100 <= 12 and 2000 <= x//100 <= 2100
    except (TypeError,ValueError):
        return False

def activity_index(records):
    indexed={}
    all_months=set()
    for item in records:
        low={str(k).lower():v for k,v in item.items()}
        tid=low.get('traderid')
        month=low.get('monthid')
        if tid is None or not valid_month(month):
            continue
        month=int(month)
        all_months.add(month)
        rec=indexed.setdefault(str(tid),[])
        rec.append((month,str(low.get('commodityid',''))))
    return indexed,all_months

def score_records(df, imports, exports):
    imp, imp_months=activity_index(imports)
    exp, exp_months=activity_index(exports)
    available=imp_months | exp_months
    if not available:
        # Cannot infer reporting coverage from empty activity responses.
        raise ValueError('No dated activity records were returned; cannot safely score traders.')
    latest=max(available)
    end_index=month_index(latest)
    window12=set(ym_from_index(i) for i in range(end_index-11,end_index+1))
    window24=set(ym_from_index(i) for i in range(end_index-23,end_index+1))
    # These are months seen anywhere in this search, NOT proof of national publication completeness.
    observed12=len(available & window12)
    observed24=len(available & window24)
    for flow,records in [('Import',imp),('Export',exp)]:
        for span,months in [(12,window12),(24,window24)]:
            df[f'{flow} active months ({span}m)']=df['Trader ID'].map(
                lambda t:len({m for m,c in records.get(str(t),[]) if m in months}))
            df[f'{flow} published lines ({span}m)']=df['Trader ID'].map(
                lambda t:sum(m in months for m,c in records.get(str(t),[])))
        df[f'{flow} distinct commodity codes (24m)']=df['Trader ID'].map(
            lambda t:len({c for m,c in records.get(str(t),[]) if m in window24 and c}))
        df[f'{flow} commodity codes (24m)']=df['Trader ID'].map(
            lambda t:', '.join(sorted({c for m,c in records.get(str(t),[]) if m in window24 and c})))
        df[f'Latest {flow.lower()}']=df['Trader ID'].map(
            lambda t:month_label(max([m for m,c in records.get(str(t),[]) if m in window24],default=None)))
        df[f'First {flow.lower()} (24m)']=df['Trader ID'].map(
            lambda t:month_label(min([m for m,c in records.get(str(t),[]) if m in window24],default=None)))
        df[f'{flow} months since last']=df['Trader ID'].map(
            lambda t:end_index-month_index(max([m for m,c in records.get(str(t),[]) if m in window24]))
            if any(m in window24 for m,c in records.get(str(t),[])) else None)
    im=df['Import active months (12m)']; ex=df['Export active months (12m)']
    im24=df['Import active months (24m)']; ex24=df['Export active months (24m)']
    df['Trade direction']=['Both' if i and e else 'Importer' if i else 'Exporter' if e else
                           'Historical / review' if a or b else 'Not observed'
                           for i,e,a,b in zip(im,ex,im24,ex24)]
    peak=pd.concat([im,ex],axis=1).max(axis=1)
    df['Tier']=peak.map(lambda n:'A' if n>=10 else 'B' if n>=4 else 'C' if n>=1 else 'Unconfirmed')
    df['Trend']=['Newer / growing' if max(i,e)>max(a-i,b-e)+2 else
                 'Reduced activity' if max(a-i,b-e)>max(i,e)+2 else
                 'Steady / mixed' if i+e+a+b else 'Unknown'
                 for i,e,a,b in zip(im,ex,im24,ex24)]
    last=df[['Import months since last','Export months since last']].min(axis=1)
    df['Recency']=last.map(lambda n:'Unknown' if pd.isna(n) else 'Recent' if n<=2 else
                            'Moderate' if n<=5 else 'Older')
    df['Sales priority']=['Research' if tier=='Unconfirmed' else
                          'High' if tier=='A' and rec=='Recent' else
                          'Medium' if tier in ('A','B') and rec in ('Recent','Moderate') else 'Low'
                          for tier,rec in zip(df['Tier'],df['Recency'])]
    df['Sales rationale']=[f'{direction}; imports {i}/12 months ({a}/24), exports {e}/12 ({b}/24); '
                           f'latest import {li}, export {le}; {trend.lower()}. Validate freight fit and CRM ownership.'
                           for direction,i,e,a,b,li,le,trend in zip(
                           df['Trade direction'],im,ex,im24,ex24,df['Latest import'],df['Latest export'],df['Trend'])]
    hs_chapters={'22':'Beverages / alcohol (review)','27':'Mineral fuels (review)',
                 '29':'Organic chemicals (review)','30':'Pharmaceuticals (review)',
                 '39':'Plastics','40':'Rubber','44':'Wood','48':'Paper / packaging',
                 '52':'Cotton / textiles','61':'Knitted apparel','62':'Woven apparel',
                 '72':'Iron / steel','73':'Iron / steel articles','76':'Aluminium',
                 '84':'Machinery','85':'Electrical equipment','87':'Vehicles / parts',
                 '90':'Precision instruments'}
    def chapters(row):
        codes=set()
        for flow in ('Import','Export'):
            codes.update(x.strip() for x in row[f'{flow} commodity codes (24m)'].split(',') if x.strip())
        return ', '.join(sorted({hs_chapters.get(code[:2],f'HS {code[:2]}') for code in codes})) or 'Unknown'
    df['Commodity groups (indicative)']=df.apply(chapters,axis=1)
    df['Specialist handling review']=df['Commodity groups (indicative)'].str.contains('(review)',regex=False).map({True:'Check capability',False:'Not flagged — still verify'})
    df['Shipment volume estimate']='Not available — commodity-month lines are not shipments'
    df['Freight spend estimate']='Not available'
    df['Site confidence']='Registered / supplied postcode — operating site unverified'
    df['CRM status']='Not checked'
    df['Contact enrichment']='Not performed'
    df['Data window end']=month_label(latest)
    return df,{'latest':latest,'months12':observed12,'months24':observed24,
               'start12':ym_from_index(end_index-11),'start24':ym_from_index(end_index-23)}

mode=st.segmented_control('Search type',['Postcode area','Radius'],default='Postcode area')
postcode=st.text_input('Postcode area / district' if mode=='Postcode area' else 'Full postcode',value='WS10' if mode=='Postcode area' else 'WS10 8AB')
if mode=='Radius':radius=st.slider('Radius in miles',1,30,10)
limit=st.select_slider('Maximum traders',options=[100,250,500,1000,2000,5000],value=500)
activity_limit=st.select_slider('Maximum activity records per direction',options=[2000,5000,10000,30000],value=10000)
with st.expander('How to interpret the evidence'):
    st.write('The app queries up to 30 calendar months of published HMRC commodity-month records and compares the latest 12 and 24 months ending with the most recent month observed in THIS search. This is a local proxy, not a verified national publication calendar.')
    st.write('Tier A: 10–12 active months in either trade direction; B: 4–9; C: 1–3. Activity is not shipment frequency or freight value. Priority is a research heuristic, not a sales forecast.')
    st.write('If a trader or activity record cap is reached, activity scores are withheld or the trader list is flagged incomplete. Registered office locations may not be freight operating sites.')

if st.button('🔎 Search HMRC traders',type='primary',use_container_width=True):
    code=clean(postcode)
    if mode=='Postcode area' and not re.fullmatch(r'[A-Z]{1,2}(\d{1,2}[A-Z]?)?',code):
        st.error('Enter an area or district such as WS or WS10.')
    elif mode=='Radius' and not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}',code):
        st.error('Enter a full postcode such as WS10 8AB.')
    else:
        try:
            prefix=code if mode=='Postcode area' else re.match(r'^[A-Z]{1,2}\d{1,2}[A-Z]?',code).group()
            if mode=='Radius':st.warning('Radius coverage is incomplete: only traders in the origin postcode district are retrieved.')
            start,end=query_window()
            incomplete=False
            st.session_state.pop('result',None)
            st.session_state.pop('coverage',None)
            with st.spinner('Retrieving HMRC traders and import/export records…'):
                traders,truncated=fetch_traders(prefix,limit)
                df=pd.DataFrame([row_to_record(t) for t in traders],columns=['Trader ID','Company','Postcode','Registered address'])
                if not df.empty:
                    if mode=='Postcode area' and re.search(r'\d',code):
                        outward=df['Postcode'].astype(str).str.upper().str.replace(' ','',regex=False).str.extract(r'^([A-Z]{1,2}\d{1,2}[A-Z]?)',expand=False)
                        df=df[outward==code].copy()
                    if mode=='Radius':
                        loc=lookup_postcodes(tuple(sorted(set([code]+[clean(x) for x in df['Postcode'].dropna()]))))
                        if code not in loc:raise ValueError('Origin postcode not found')
                        df['Miles away']=df['Postcode'].map(lambda x:round(distance(loc[code],loc[clean(x)]),1) if clean(x) in loc else float('nan'))
                        df=df[df['Miles away']<=radius].copy()
                    imports,imp_cap=fetch_activity(prefix,'Import',start,end,activity_limit)
                    exports,exp_cap=fetch_activity(prefix,'Export',start,end,activity_limit)
                    incomplete=imp_cap or exp_cap
                    if not incomplete:
                        df,coverage=score_records(df,imports,exports)
                        st.session_state['coverage']=coverage
                    else:
                        st.warning('Activity record cap reached. Activity and tiers are withheld to avoid misleading rankings. Increase the activity limit or narrow the postcode search.')
                    st.session_state['activity_incomplete']=incomplete
            st.session_state['result']=df
            st.session_state['truncated']=truncated
            st.session_state['period']=(start,end)
            st.session_state['activity_incomplete']=incomplete
        except Exception as exc:
            st.error(f'HMRC search failed: {exc}')
            st.info('The live API activity queries need validation on your deployed app. Check the app logs if this persists.')

if 'result' in st.session_state:
    df=st.session_state['result'].copy()
    coverage=st.session_state.get('coverage') if not st.session_state.get('activity_incomplete') else None
    if st.session_state.get('truncated'):
        st.warning('Trader retrieval hit the selected cap: this is a PARTIAL list, not all traders in the territory.')
    if st.session_state.get('activity_incomplete'):
        st.error('Activity API cap reached. Activity scores were withheld to prevent misleading prioritisation. Narrow the territory or increase the cap.')
    if coverage:
        st.info(f"Trade evidence ends {month_label(coverage['latest'])} (latest observed in this search). "
                f"Observed months in this search: {coverage['months12']}/12 and {coverage['months24']}/24. "
                'This does not independently verify HMRC publication coverage.')
        with st.expander('Sales filters',expanded=False):
            direction=st.selectbox('Trade direction',['All','Importer','Exporter','Both','Historical / review','Not observed'])
            tiers=st.multiselect('Activity tier',['A','B','C','Unconfirmed'],default=['A','B','C','Unconfirmed'])
            priorities=st.multiselect('Sales priority',['High','Medium','Low','Research'],default=['High','Medium','Low','Research'])
            trends=st.multiselect('12m versus prior 12m',['Newer / growing','Steady / mixed','Reduced activity','Unknown'],default=['Newer / growing','Steady / mixed','Reduced activity','Unknown'])
            min_months=st.slider('Minimum import OR export active months (12m)',0,12,0)
            exclude=st.text_input('Exclude commodity code prefixes (comma-separated, e.g. 22)',value='')
        if direction=='Importer':df=df[df['Import active months (12m)']>0]
        elif direction=='Exporter':df=df[df['Export active months (12m)']>0]
        elif direction!='All':df=df[df['Trade direction']==direction]
        df=df[df['Tier'].isin(tiers)&df['Sales priority'].isin(priorities)&df['Trend'].isin(trends)]
        df=df[df[['Import active months (12m)','Export active months (12m)']].max(axis=1)>=min_months]
        terms=[x.strip() for x in exclude.split(',') if x.strip()]
        if terms:
            import re as _re
            for term in terms:
                # Compare commodity codes as individual tokens; avoid partial matches mid-code.
                pat=r'(?<!\d)'+_re.escape(term)
                df=df[~(df['Import commodity codes (24m)'].str.contains(pat,regex=True,na=False) |
                        df['Export commodity codes (24m)'].str.contains(pat,regex=True,na=False))]
        rank={'High':0,'Medium':1,'Low':2,'Research':3}
        df=df.assign(_rank=df['Sales priority'].map(rank)).sort_values(
            ['_rank','Import active months (12m)','Export active months (12m)'],
            ascending=[True,False,False]).drop(columns='_rank')
    a,b,c=st.columns(3)
    a.metric('Prospects',f'{len(df):,}')
    b.metric('A-tier',f'{(df["Tier"]=="A").sum():,}' if 'Tier' in df else '—')
    c.metric('High priority',f'{(df["Sales priority"]=="High").sum():,}' if 'Sales priority' in df else '—')
    if df.empty:
        st.info('No matching records. Try changing filters or territory.')
    else:
        focus=['Company','Postcode','Trade direction','Tier','Sales priority',
               'Import active months (12m)','Export active months (12m)',
               'Import active months (24m)','Export active months (24m)',
               'Latest import','Latest export','Trend','Commodity groups (indicative)','Specialist handling review','Sales rationale']
        st.subheader('Prospect shortlist')
        st.dataframe(df[[x for x in focus if x in df]],hide_index=True,use_container_width=True)
        with st.expander('Full analytical dataset'):
            st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('⬇️ Export sales-ready CSV',
            df[[x for x in focus if x in df]+['Trader ID','Registered address','CRM status','Site confidence','Contact enrichment']].to_csv(index=False).encode('utf-8-sig'),
            'hmrc_sales_ready_v4.csv','text/csv',use_container_width=True)
        st.download_button('⬇️ Export full evidence CSV',
            df.to_csv(index=False).encode('utf-8-sig'),
            'hmrc_full_evidence_v4.csv','text/csv',use_container_width=True)
        st.caption('AI enrichment: upload sales-ready CSV only to an organisation-approved platform; verify company identity, freight suitability and CRM ownership before outreach.')
st.divider()
st.caption('V4 prototype · HMRC API and reporting coverage require live validation · Radius mode is NOT a complete geographical search · No shipment counts or spend estimates are inferred.')
