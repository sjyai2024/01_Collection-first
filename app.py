import streamlit as st
import requests, re, time, io, zipfile, json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
import pandas as pd
from datetime import datetime

APP_VERSION="2.8"
st.set_page_config(page_title="01 Brand Text Collector v2.8", layout="wide")

BRAND_KEYS=[
    "about","brand","story","our-story","brand-story","philosophy","mission","vision",
    "values","heritage","identity","concept","purpose","소개","브랜드","스토리","철학",
    "미션","비전","가치","정체성"
]
EXCLUDE_KEYS=[
    "product","products","shop","store","collection","ingredient","ingredients","review",
    "reviews","news","press","event","faq","login","account","cart","checkout","privacy",
    "terms","제품","상품","성분","효능","사용법","리뷰","뉴스","이벤트","장바구니",
    "로그인","개인정보","약관"
]
PRODUCT_TERMS=[
    "제품","성분","효능","사용법","ingredient","ingredients","formula","formulation",
    "clinical","dermatologist","피부과","전문의","스킨케어","토너","세럼","앰플",
    "선크림","spf","product","products"
]
UI_TERMS=[
    "visit and follow us","brand core value","learn more","shop now","view more",
    "discover more"
]
UA="AcademicBrandTextCollector/2.8 (+research-use)"
HEADERS={"User-Agent":UA}

def clean(u):
    return urldefrag(str(u))[0].rstrip("/")

def domain(u):
    return urlparse(str(u)).netloc.lower().replace("www.","")

@st.cache_data(ttl=3600, show_spinner=False)
def robots_ok_cached(base_robots_url, target_url):
    try:
        rp=RobotFileParser()
        rp.set_url(base_robots_url)
        rp.read()
        return rp.can_fetch(UA,target_url)
    except Exception:
        return True

def robots_ok(u):
    p=urlparse(u)
    return robots_ok_cached(f"{p.scheme}://{p.netloc}/robots.txt",u)

def fetch(u):
    if not robots_ok(u):
        raise PermissionError("robots.txt에서 자동수집을 허용하지 않습니다.")
    r=requests.get(u,headers=HEADERS,timeout=20,allow_redirects=True)
    r.raise_for_status()
    ct=r.headers.get("content-type","")
    if "text/html" not in ct:
        return None,"",r.url,r.status_code,ct
    s=BeautifulSoup(r.text,"html.parser")
    title=s.title.get_text(" ",strip=True) if s.title else ""
    return s,title,r.url,r.status_code,ct

def infer_brand(soup,title,url):
    vals=[]
    try:
        for tag in soup.find_all("script",type="application/ld+json"):
            try:
                data=json.loads(tag.string or "{}")
                items=data if isinstance(data,list) else [data]
                for item in items:
                    if isinstance(item,dict):
                        if item.get("@type") in ["Organization","WebSite","Brand"] and item.get("name"):
                            vals.append(str(item["name"]).strip())
                        pub=item.get("publisher")
                        if isinstance(pub,dict) and pub.get("name"):
                            vals.append(str(pub["name"]).strip())
            except Exception:
                pass
    except Exception:
        pass
    for attrs in [
        {"property":"og:site_name"},{"name":"application-name"},
        {"name":"apple-mobile-web-app-title"}
    ]:
        m=soup.find("meta",attrs=attrs)
        if m and m.get("content"):
            vals.append(m["content"].strip())
    if title:
        vals += [x.strip() for x in re.split(r"\s*[|–—]\s*",title) if x.strip()]
    bad={"official","official site","official website","home","홈","공식몰","온라인몰","korea","global"}
    for v in vals:
        vv=re.sub(r"\s+(official|official site|official website|공식몰|온라인몰)$","",v,flags=re.I).strip()
        if 1<len(vv)<=60 and vv.lower() not in bad:
            return vv
    host=domain(url).split(".")[0]
    return host.replace("-"," ").replace("_"," ").strip().title()

def ptype(u,title="",anchor=""):
    h=f"{u} {title} {anchor}".lower()
    mp=[
        ("Philosophy",["philosophy","철학"]),
        ("Mission",["mission","미션"]),
        ("Vision",["vision","비전"]),
        ("Values",["values","가치"]),
        ("Brand Story",["story","스토리"]),
        ("Heritage",["heritage"]),
        ("About",["about","소개"]),
        ("Brand",["brand","브랜드","identity","정체성","purpose","concept"])
    ]
    for lab,ks in mp:
        if any(k in h for k in ks):
            return lab
    return "Homepage"

def candidate(u,t=""):
    h=f"{u} {t}".lower()
    return not any(k in h for k in EXCLUDE_KEYS) and any(k in h for k in BRAND_KEYS)

def extract(s):
    if s is None:
        return ""
    for tag in s(["script","style","noscript","svg","form"]):
        tag.decompose()
    for sel in ["nav","footer"]:
        for x in s.select(sel):
            x.decompose()
    root=s.find("main") or s.find("article") or s.body or s
    out=[];seen=set()
    for e in root.find_all(["h1","h2","h3","h4","p","li","blockquote"]):
        t=re.sub(r"\s+"," "," ".join(e.stripped_strings)).strip()
        if len(t)>=15 and t.casefold() not in seen:
            seen.add(t.casefold());out.append(t)
    return "\n".join(out)

def split_units(text):
    blocks=[re.sub(r"[ \t]+"," ",x).strip() for x in re.split(r"\n+",str(text)) if x.strip()]
    out=[]
    for b in blocks:
        parts=[b] if len(b)<=280 else re.split(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+",b)
        out.extend([re.sub(r"\s+"," ",p).strip() for p in parts if len(p.strip())>=15])
    return list(dict.fromkeys(out))

def crawl_site(url, brand_override="", max_pages=15, delay=.15):
    if not str(url).startswith(("http://","https://")):
        url="https://"+str(url)
    seed_url=clean(url)
    started=datetime.now().isoformat(timespec="seconds")
    soup,title,final,status_code,ct=fetch(seed_url)
    auto_brand=infer_brand(soup,title,final) if soup else ""
    brand=str(brand_override).strip() or auto_brand

    # Seed page + brand-related internal links discovered from it.
    found={clean(final):("SEED",title,"")}
    if soup:
        for a in soup.find_all("a",href=True):
            u=clean(urljoin(final,a["href"]))
            txt=a.get_text(" ",strip=True)
            if u.startswith(("http://","https://")) and domain(u)==domain(final) and candidate(u,txt):
                found[u]=(ptype(u,anchor=txt),txt,"")

    rows=[]
    day=datetime.now().strftime("%Y-%m-%d")
    for i,(u,(_,anchor,_)) in enumerate(list(found.items())[:max_pages],1):
        row={
            "Brand":brand,"Auto_Brand_Name":auto_brand,"Seed_URL":seed_url,
            "Page_ID":f"{re.sub(r'[^A-Za-z0-9]+','_',brand).strip('_')[:30]}_P{i:03d}",
            "Page_Type":"","Page_Title":"","Source_URL":u,"Collection_Date":day,
            "Original_Text":"","Character_Count":0,"Fetch_Status":"","HTTP_Status":"",
            "Content_Type":"","Auto_Include":0,"Researcher_Final":0,
            "Researcher_Note":"","Error_Message":""
        }
        try:
            s,t,fu,http_status,ctype=fetch(u)
            txt=extract(s)
            pt=ptype(fu,t,anchor)
            auto=1 if pt!="Homepage" else 0
            row.update({
                "Page_Type":pt,"Page_Title":t,"Source_URL":fu,
                "Original_Text":txt,"Character_Count":len(txt),
                "Fetch_Status":"OK" if len(txt)>=50 else "LOW_TEXT",
                "HTTP_Status":http_status,"Content_Type":ctype,
                "Auto_Include":auto,"Researcher_Final":auto,
            })
        except PermissionError as e:
            row.update({"Page_Type":"ERROR","Fetch_Status":"ROBOTS_BLOCKED","Error_Message":str(e)})
        except Exception as e:
            row.update({"Page_Type":"ERROR","Fetch_Status":"ERROR","Error_Message":repr(e)})
        rows.append(row)
        time.sleep(delay)
    return brand,auto_brand,pd.DataFrame(rows),started

def unit_table(pages):
    rows=[];cnt={}
    if len(pages)==0:
        return pd.DataFrame()
    approved=pages[pd.to_numeric(pages["Researcher_Final"],errors="coerce").fillna(0).astype(int)==1]
    for _,r in approved.iterrows():
        b=r["Brand"];cnt.setdefault(b,0)
        for t in split_units(r["Original_Text"]):
            cnt[b]+=1;tl=t.lower()
            if len(t)<35 or any(x in tl for x in UI_TERMS):
                cat,auto,why="UI/Heading",0,"UI/섹션 제목 후보"
            elif any(x in tl for x in PRODUCT_TERMS):
                cat,auto,why="Product/Functional",0,"제품·기능 관련 후보"
            else:
                cat,auto,why="Brand",1,"브랜드 정체성·철학·가치 후보"
            rows.append({
                "Brand":b,"Unit_ID":f"{re.sub(r'[^A-Za-z0-9]+','_',b).strip('_')[:30]}_U{cnt[b]:04d}",
                "Page_ID":r["Page_ID"],"Source_URL":r["Source_URL"],"Text":t,
                "Auto_Category":cat,"Auto_Include":auto,"Researcher_Final":auto,
                "Review_Reason":why,"Researcher_Note":""
            })
    return pd.DataFrame(rows)

def to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8-sig")

st.title("01 Brand Text Collector · v2.8")
st.caption("수집 우선 모드: 68개 공식 사이트를 배치 수집 → 원자료/오류 로그 저장 → 이후 페이지·Unit 검토")

if "raw_pages" not in st.session_state:
    st.session_state.raw_pages=pd.DataFrame()
if "crawl_status" not in st.session_state:
    st.session_state.crawl_status=pd.DataFrame()

tab1,tab2,tab3=st.tabs(["① 배치 원자료 수집","② 수집 현황·원자료 다운로드","③ 페이지·Unit 검토"])

with tab1:
    st.subheader("배치 원자료 수집")
    seed_file=st.file_uploader(
        "Seed CSV 업로드",
        type=["csv"],
        help="필수 열: Brand, Seed_URL. 선택 열: Collect, Eligibility, URL_Status, Research_Note"
    )
    if seed_file:
        seed=pd.read_csv(seed_file)
        required={"Brand","Seed_URL"}
        if not required.issubset(seed.columns):
            st.error("Seed CSV에는 Brand, Seed_URL 열이 필요합니다.")
            st.stop()
        if "Collect" not in seed:
            seed["Collect"]=1
        seed["Collect"]=pd.to_numeric(seed["Collect"],errors="coerce").fillna(0).astype(int)
        work=seed[(seed["Collect"]==1)&seed["Seed_URL"].fillna("").astype(str).str.strip().ne("")].reset_index(drop=True)
        st.write(f"수집 가능한 seed: **{len(work)}개** / 전체 {len(seed)}개")
        if len(work):
            c1,c2,c3=st.columns(3)
            with c1:
                batch_size=st.number_input("배치 크기",min_value=1,max_value=20,value=min(10,len(work)),step=1)
            with c2:
                batch_no=st.number_input("배치 번호",min_value=1,max_value=max(1,(len(work)+batch_size-1)//batch_size),value=1,step=1)
            with c3:
                max_pages=st.number_input("브랜드당 최대 페이지",min_value=1,max_value=30,value=15,step=1)
            start=(batch_no-1)*batch_size
            stop=min(start+batch_size,len(work))
            batch=work.iloc[start:stop]
            st.dataframe(batch[[c for c in ["Brand","Seed_URL","Eligibility","URL_Status"] if c in batch]],use_container_width=True,hide_index=True)
            st.warning("68개를 한 번에 실행하지 말고 8~12개 단위로 수집하는 것을 권장합니다. 일부 사이트는 robots.txt·Cloudflare·JavaScript 때문에 실패할 수 있으며 실패 자체를 로그로 보존합니다.")
            if st.button(f"배치 {int(batch_no)} 수집 시작",type="primary"):
                new_pages=[];new_status=[]
                progress=st.progress(0)
                status_box=st.empty()
                for n,(_,r) in enumerate(batch.iterrows(),1):
                    brand=str(r["Brand"]).strip()
                    url=str(r["Seed_URL"]).strip()
                    status_box.write(f"{n}/{len(batch)} · {brand} 수집 중")
                    try:
                        b,auto,pages,started=crawl_site(url,brand_override=brand,max_pages=int(max_pages))
                        new_pages.append(pages)
                        new_status.append({
                            "Brand":brand,"Seed_URL":url,"Auto_Brand_Name":auto,
                            "Started_At":started,"Finished_At":datetime.now().isoformat(timespec="seconds"),
                            "Status":"OK" if (pages["Fetch_Status"]=="OK").any() else "CHECK",
                            "N_Pages":len(pages),
                            "N_OK":int((pages["Fetch_Status"]=="OK").sum()),
                            "N_Low_Text":int((pages["Fetch_Status"]=="LOW_TEXT").sum()),
                            "N_Error":int(pages["Fetch_Status"].isin(["ERROR","ROBOTS_BLOCKED"]).sum()),
                            "Total_Characters":int(pd.to_numeric(pages["Character_Count"],errors="coerce").fillna(0).sum())
                        })
                    except Exception as e:
                        new_status.append({
                            "Brand":brand,"Seed_URL":url,"Auto_Brand_Name":"",
                            "Started_At":"","Finished_At":datetime.now().isoformat(timespec="seconds"),
                            "Status":"FAILED","N_Pages":0,"N_OK":0,"N_Low_Text":0,"N_Error":1,
                            "Total_Characters":0,"Error_Message":repr(e)
                        })
                    progress.progress(n/len(batch))
                if new_pages:
                    npages=pd.concat(new_pages,ignore_index=True)
                    if len(st.session_state.raw_pages):
                        combined=pd.concat([st.session_state.raw_pages,npages],ignore_index=True)
                        combined=combined.drop_duplicates(["Brand","Source_URL"],keep="last")
                    else:
                        combined=npages
                    st.session_state.raw_pages=combined.reset_index(drop=True)
                ns=pd.DataFrame(new_status)
                if len(st.session_state.crawl_status):
                    combined_s=pd.concat([st.session_state.crawl_status,ns],ignore_index=True)
                    combined_s=combined_s.drop_duplicates(["Brand"],keep="last")
                else:
                    combined_s=ns
                st.session_state.crawl_status=combined_s.reset_index(drop=True)
                st.success("배치 수집 완료. ② 탭에서 원자료를 다운로드하세요.")

with tab2:
    st.subheader("수집 현황")
    # Allow continuing across Streamlit sessions by importing accumulated files.
    c1,c2=st.columns(2)
    with c1:
        import_pages=st.file_uploader("이전 raw_pages CSV 불러오기",type=["csv"],key="import_raw")
    with c2:
        import_status=st.file_uploader("이전 crawl_status CSV 불러오기",type=["csv"],key="import_status")
    if import_pages is not None:
        old=pd.read_csv(import_pages)
        st.session_state.raw_pages=old
        st.success(f"raw_pages {len(old)}행 불러옴")
    if import_status is not None:
        old_s=pd.read_csv(import_status)
        st.session_state.crawl_status=old_s
        st.success(f"crawl_status {len(old_s)}행 불러옴")

    if len(st.session_state.crawl_status):
        st.dataframe(st.session_state.crawl_status,use_container_width=True,hide_index=True)
    else:
        st.info("아직 수집 상태가 없습니다.")

    if len(st.session_state.raw_pages):
        raw=st.session_state.raw_pages.copy()
        st.write(f"누적 **{raw['Brand'].nunique()}개 브랜드 / {len(raw)}개 페이지**")
        summ=raw.groupby("Brand").agg(
            Pages=("Page_ID","count"),
            OK=("Fetch_Status",lambda s:int((s=="OK").sum())),
            Auto_Brand_Pages=("Auto_Include","sum"),
            Characters=("Character_Count","sum")
        ).reset_index()
        st.dataframe(summ,use_container_width=True,hide_index=True)

        st.download_button("raw pages CSV",to_csv_bytes(raw),"01_raw_pages_v2_8.csv","text/csv")
        if len(st.session_state.crawl_status):
            st.download_button("crawl status CSV",to_csv_bytes(st.session_state.crawl_status),"01_crawl_status_v2_8.csv","text/csv")

        bio=io.BytesIO()
        with zipfile.ZipFile(bio,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("01_raw_pages_v2_8.csv",to_csv_bytes(raw))
            if len(st.session_state.crawl_status):
                z.writestr("01_crawl_status_v2_8.csv",to_csv_bytes(st.session_state.crawl_status))
        st.download_button("원자료 ZIP",bio.getvalue(),"01_collection_raw_v2_8.zip","application/zip")
    else:
        st.info("① 탭에서 먼저 수집하세요.")

with tab3:
    st.subheader("수집 후 페이지·Content Unit 검토")
    review_file=st.file_uploader("검토할 raw_pages CSV",type=["csv"],key="review_raw")
    if review_file:
        pages=pd.read_csv(review_file)
    elif len(st.session_state.raw_pages):
        pages=st.session_state.raw_pages.copy()
    else:
        pages=pd.DataFrame()

    if len(pages):
        brands=pages["Brand"].dropna().astype(str).unique().tolist()
        selected=st.selectbox("검토 브랜드",brands)
        sub=pages[pages["Brand"].astype(str)==selected].copy()
        st.caption("원자료 수집이 끝난 뒤 페이지 판정 규칙을 점검·수정하는 단계입니다.")
        ep=st.data_editor(
            sub,
            disabled=[c for c in sub.columns if c not in ["Researcher_Final","Researcher_Note"]],
            column_config={
                "Researcher_Final":st.column_config.NumberColumn("연구자 확인 (0/1)",min_value=0,max_value=1,step=1,format="%d"),
                "Researcher_Note":st.column_config.TextColumn("연구자 메모")
            },
            use_container_width=True,height=380,hide_index=True,key=f"review_{selected}"
        )
        ep["Researcher_Final"]=pd.to_numeric(ep["Researcher_Final"],errors="coerce").fillna(0).clip(0,1).astype(int)
        units=unit_table(ep)
        st.write(f"현재 승인 페이지 {int(ep['Researcher_Final'].sum())}개 → 생성 Content Unit {len(units)}개")
        if len(units):
            eu=st.data_editor(
                units,
                disabled=[c for c in units.columns if c not in ["Researcher_Final","Researcher_Note"]],
                column_config={
                    "Researcher_Final":st.column_config.NumberColumn("연구자 최종 (0/1)",min_value=0,max_value=1,step=1,format="%d"),
                    "Researcher_Note":st.column_config.TextColumn("연구자 메모")
                },
                use_container_width=True,height=420,hide_index=True,key=f"unit_{selected}"
            )
            eu["Researcher_Final"]=pd.to_numeric(eu["Researcher_Final"],errors="coerce").fillna(0).clip(0,1).astype(int)
            approved=eu[eu["Researcher_Final"]==1].copy()
            if len(approved):
                approved["Word_Count"]=approved["Text"].astype(str).str.split().str.len()
                approved["Character_Count"]=approved["Text"].astype(str).str.len()
            st.download_button(
                f"{selected} 승인 Unit CSV",
                to_csv_bytes(approved),
                f"01_{re.sub(r'[^A-Za-z0-9]+','_',selected).strip('_')}_approved_units.csv",
                "text/csv"
            )

st.divider()
st.caption(
    "v2.8 연구원칙: 먼저 원자료를 최대한 수집하고, 수집률·텍스트량·오류유형을 확인한 뒤 "
    "자동 페이지/Unit 판정 규칙을 수정한다. 02 분석식은 corpus 진단 전 확정하지 않는다."
)
