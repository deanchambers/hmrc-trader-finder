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
st.title('🚢 UK Freight Sales Intelligence')
st.caption('Live HMRC trader discovery · Sales qualification · Mobile-friendly')

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

def last_12_months():
    today=date.today()
    end_index=today.year*12+today.month-2
    def to_ym(index):
        return (index//12)*100 + index%12+1
    return to_ym(end_index-11),to_ym(end_index)

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
        return "Not observed"
    raw = str(int(value))
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 6 else raw

def month_index(value):
    value = int(value)
    return (value // 100) * 12 + (value % 100)

def enrich_activity(df, imports, exports, end_month):
    for flow, records in [("Import", imports), ("Export", exports)]:
        activity = {}
        for record in records:
            low = {str(k).lower(): v for k, v in record.items()}
            trader = low.get("traderid")
            if trader is None:
                continue
            key = str(trader)
            bucket = activity.setdefault(key, {"months": set(), "commodities": set(), "lines": 0})
            month = low.get("monthid")
            if month is not None:
                try:
                    bucket["months"].add(int(month))
                except (TypeError, ValueError):
                    pass
            commodity = low.get("commodityid")
            if commodity is not None:
                bucket["commodities"].add(str(commodity))
            bucket["lines"] += 1

        def get(trader):
            return activity.get(str(trader), {"months": set(), "commodities": set(), "lines": 0})

        df[flow + " active months (12m)"] = df["Trader ID"].map(lambda t: len(get(t)["months"]))
        df[flow + " published lines (12m)"] = df["Trader ID"].map(lambda t: get(t)["lines"])
        df[flow + " distinct commodity codes"] = df["Trader ID"].map(lambda t: len(get(t)["commodities"]))
        df[flow + " commodity IDs"] = df["Trader ID"].map(lambda t: ", ".join(sorted(get(t)["commodities"]))[:1500])
        df["First " + flow.lower() + " (12m)"] = df["Trader ID"].map(
            lambda t: month_label(min(get(t)["months"])) if get(t)["months"] else "Not observed")
        df["Latest " + flow.lower() + " (12m)"] = df["Trader ID"].map(
            lambda t: month_label(max(get(t)["months"])) if get(t)["months"] else "Not observed")
        df[flow + " months since last seen"] = df["Trader ID"].map(
            lambda t: month_index(end_month) - month_index(max(get(t)["months"]))
            if get(t)["months"] else None)

    im = df["Import active months (12m)"]
    ex = df["Export active months (12m)"]
    df["Trade direction"] = [
        "Both" if i and e else "Importer" if i else "Exporter" if e else "Not observed"
        for i, e in zip(im, ex)
    ]
    peak = pd.concat([im, ex], axis=1).max(axis=1)
    df["Tier"] = peak.map(lambda n: "A" if n >= 10 else "B" if n >= 4 else "C" if n >= 1 else "Unconfirmed")
    df["Import status"] = ["Observed" if x else "Not observed" for x in im]
    df["Export status"] = ["Observed" if x else "Not observed" for x in ex]
    recent = df[["Import months since last seen", "Export months since last seen"]].min(axis=1)
    df["Recency"] = recent.map(
        lambda n: "No evidence" if pd.isna(n) else "Recent" if n <= 2 else "Older" if n <= 5 else "Stale")
    df["Priority"] = [
        "High" if tier == "A" and rec == "Recent" else
        "Medium" if tier in ("A", "B") and rec in ("Recent", "Older") else
        "Review" if tier == "Unconfirmed" else "Low"
        for tier, rec in zip(df["Tier"], df["Recency"])
    ]
    df["Why contact"] = [
        f"{direction}; imports observed in {int(i)}/12 months; exports observed in {int(e)}/12 months; "
        f"last import {li}; last export {le}; {rec.lower()} activity. "
        "Commodity-month records do not measure shipment volumes."
        for direction, i, e, li, le, rec in zip(
            df["Trade direction"], im, ex, df["Latest import (12m)"],
            df["Latest export (12m)"], df["Recency"])
    ]
    df["Estimated shipment count"] = "Unavailable from HMRC trader data"
    df["Estimated freight value"] = "Unavailable from HMRC trader data"
    return df

mode=st.segmented_control('Search type',['Postcode area','Radius'],default='Postcode area')
postcode=st.text_input('Postcode area / district' if mode=='Postcode area' else 'Full postcode',value='WS10' if mode=='Postcode area' else 'WS10 8AB')
if mode=='Radius':radius=st.slider('Radius in miles',1,30,10)
limit=st.select_slider('Maximum traders',options=[100,250,500,1000,2000,5000],value=500)
activity_limit=st.select_slider('Maximum activity records per direction',options=[2000,5000,10000,30000],value=10000)
with st.expander('About the activity metrics'):
    st.write('Activity is counted from distinct published commodity-month records over the last 12 complete calendar months. A=10–12 months in either direction, B=4–9, C=1–3. One record is NOT one shipment. No observed trade does not prove no trading.')
    st.write('High priority = A-tier with activity observed within 2 months of the latest complete calendar month. Medium = A/B with activity within 5 months. This is a configurable prospecting heuristic, not a freight-volume estimate.')
    st.write('If trader or activity results are capped, the list is incomplete. Registered addresses may not be operating sites. HMRC does not provide reliable shipment volumes or values here.')

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
            start,end=last_12_months()
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
                        df=enrich_activity(df,imports,exports,end)
                    else:
                        st.warning('Activity record cap reached. Activity and tiers are withheld to avoid misleading rankings. Increase the activity limit or narrow the postcode search.')
                    st.session_state['activity_incomplete']=incomplete
            st.session_state['result']=df
            st.session_state['truncated']=truncated
            st.session_state['period']=(start,end)
        except Exception as exc:
            st.error(f'HMRC search failed: {exc}')
            st.info('The live API activity queries need validation on your deployed app. Check the app logs if this persists.')

if 'result' in st.session_state:
    df=st.session_state['result'].copy()
    st.caption('12-month activity window: '+str(st.session_state['period'][0])+'–'+str(st.session_state['period'][1])+' (calendar months, not necessarily published months)')
    if st.session_state.get('truncated'):st.warning('Trader record limit reached; company results may be incomplete.')
    if 'Trade direction' in df.columns:
        direction=st.selectbox('Trade direction',['All','Importer','Exporter','Both'])
        tiers=st.multiselect('Priority tier',['A','B','C','Unconfirmed'],default=['A','B','C','Unconfirmed'])
        if direction=='Importer':df=df[df['Import months']>0]
        elif direction=='Exporter':df=df[df['Export months']>0]
        elif direction=='Both':df=df[df['Trade direction']=='Both']
        df=df[df['Tier'].isin(tiers)]
        df=df.sort_values(['Import months','Export months'],ascending=[False,False])
    if "Trade direction" in df.columns:
        priority = st.multiselect("Sales priority", ["High", "Medium", "Low", "Review"],
                                  default=["High", "Medium", "Low", "Review"])
        df = df[df["Priority"].isin(priority)]
        recent_only = st.checkbox("Only show companies with recent activity (last 3 published months)")
        if recent_only:
            df = df[df["Recency"] == "Recent"]
        commodity_exclude = st.text_input("Exclude commodity ID keywords (comma-separated)", "")
        for term in [s.strip() for s in commodity_exclude.split(",") if s.strip()]:
            df = df[~(df["Import commodity IDs"].str.contains(term, case=False, regex=False, na=False) |
                      df["Export commodity IDs"].str.contains(term, case=False, regex=False, na=False))]
        order = {"High": 0, "Medium": 1, "Low": 2, "Review": 3}
        df["_sort"] = df["Priority"].map(order)
        df = df.sort_values(["_sort", "Import active months (12m)", "Export active months (12m)"],
                            ascending=[True, False, False]).drop(columns="_sort")
    a,b=st.columns(2)
    a.metric('Traders',f'{len(df):,}')
    b.metric('Tier A',f'{(df["Tier"]=="A").sum():,}' if 'Tier' in df else '—')
    if df.empty:st.info('No matching traders found.')
    else:
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('⬇️ Download sales prospect CSV',df.to_csv(index=False).encode('utf-8-sig'),'hmrc_sales_prospects.csv','text/csv',use_container_width=True)

st.divider()
st.caption('Test release: HMRC activity endpoint queries still require validation on your deployed site. No shipment quantities, freight values, or decision-maker contacts are inferred. Radius coverage remains incomplete.')
