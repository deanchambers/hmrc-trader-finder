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
st.title('🚢 UK Trader Finder')
st.caption('HMRC trader discovery · Mobile-friendly prototype')

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

mode=st.segmented_control('Search type',['Postcode area','Radius'],default='Postcode area')
postcode=st.text_input('Postcode area / district' if mode=='Postcode area' else 'Full postcode',value='WS10' if mode=='Postcode area' else 'WS10 8AB',help='Area: WS, district: WS10. Radius requires a complete postcode.')
if mode=='Radius':radius=st.slider('Radius in miles',1,30,10)
limit=st.select_slider('Maximum records',options=[100,250,500,1000,2000,5000],value=1000)
with st.expander('Filters and data notes'):
    st.write('This first mobile version retrieves trader names and registered postcodes from HMRC. It does not yet retrieve import/export month counts or commodity data, so it does **not** invent A/B/C scores.')
    st.write('HMRC data may be capped or delayed; registered addresses may not represent warehouses. Search results are not necessarily a complete population of traders.')

if st.button('🔎 Search HMRC traders',type='primary',use_container_width=True):
    code=clean(postcode)
    if mode=='Postcode area' and not re.fullmatch(r'[A-Z]{1,2}(\d{1,2}[A-Z]?)?',code):
        st.error('Enter a postcode area or district, for example WS or WS10.')
    elif mode=='Radius' and not re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}',code):
        st.error('Enter a full UK postcode, for example WS10 8AB.')
    else:
        try:
            prefix=code if mode=='Postcode area' else re.match(r'^[A-Z]{1,2}\d{1,2}[A-Z]?',code).group()
            if mode=='Radius':
                st.warning('Radius search is experimental: it currently searches the origin postcode district only. Nearby districts may be missing. Do not treat this as a complete radius list.')
            with st.spinner('Connecting to HMRC…'):
                rows,truncated=fetch_traders(prefix,limit)
            df=pd.DataFrame([row_to_record(t) for t in rows],columns=['Trader ID','Company','Postcode','Registered address'])
            if mode=='Postcode area' and re.search(r'\d',code) and not df.empty:
                outward=df['Postcode'].astype(str).str.upper().str.replace(' ','',regex=False).str.extract(r'^([A-Z]{1,2}\d{1,2}[A-Z]?)',expand=False)
                df=df[outward==code]
            if mode=='Radius' and not df.empty:
                loc=lookup_postcodes(tuple(sorted(set([code]+[clean(x) for x in df['Postcode'].dropna()]))))
                if code not in loc:
                    st.error('Could not locate the search postcode.');st.stop()
                df['Miles away']=df['Postcode'].map(lambda x:round(distance(loc[code],loc[clean(x)]),1) if clean(x) in loc else float('nan'))
                df=df[df['Miles away']<=radius].sort_values('Miles away')
            st.session_state['result']=df
            st.session_state['truncated']=truncated
            st.session_state['search_label']=postcode
        except Exception as e:
            st.error(f'Live HMRC search could not be completed: {e}')
            st.info('The HMRC API connection and field mapping still need validation against a live response. No sample companies are shown as real results.')

if 'result' in st.session_state:
    df=st.session_state['result']
    a,b=st.columns(2)
    a.metric('Trader records',f'{len(df):,}')
    b.metric('Unique companies',f'{df["Company"].nunique():,}' if not df.empty else '0')
    if st.session_state['truncated']:st.warning('Record limit reached: results may be incomplete.')
    if df.empty:st.info('No matching traders were returned.')
    else:
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('⬇️ Download CSV',data=df.to_csv(index=False).encode('utf-8-sig'),file_name='hmrc_traders.csv',mime='text/csv',use_container_width=True)

st.divider()
st.caption('Prototype, not yet validated end-to-end with the HMRC service. No contact enrichment, activity scoring, or CRM integration is included yet.')
