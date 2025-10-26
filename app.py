# app.py — Pengumuman Hasil Try Out SMPN 1 SOOKO
# ------------------------------------------------
# Cara pakai (Windows PowerShell):
#  1) Simpan file Excel di: data/Hasil Tryout TKA Bimbel Brawijaya SMPN 1 Sooko.xlsx
#  2) Sesuaikan DATA_PATH jika namanya berbeda
#  3) streamlit run app.py
#
# Kolom yang dikenali (boleh salah satu):
#   Nama    : ["Nama", "Nama Lengkap", "Nama_Lengkap", "Siswa", "Full Name"]
#   No Urut : ["No", "No Urut", "Nomor", "Nomor Urut", "Urut"]
#   Skor    : ["Skor Akhir","Nilai Akhir","Nilai Total","Total","Score","Skor"]
# Jika "Skor Akhir" tidak ada, aplikasi menghitung rata-rata dari semua kolom numerik.

import re
import unicodedata
from typing import List, Tuple, Optional

import pandas as pd
import streamlit as st
from rapidfuzz import process, fuzz

st.set_page_config(
    page_title="Pengumuman Hasil Try Out • SMPN 1 Sooko",
    page_icon="📊",
    layout="centered",
)

# =================== KONFIGURASI SUMBER DATA ===================
DATA_PATH = "data/Hasil Tryout TKA Bimbel Brawijaya SMPN 1 Sooko.xlsx"

# =================== UTIL ===================
NAME_CANDS = ["nama", "nama lengkap", "nama_lengkap", "siswa", "full name"]
NO_CANDS = ["no", "no urut", "nomor", "nomor urut", "urut"]
FINAL_CANDS = ["skor akhir", "nilai akhir", "nilai total", "total", "score", "skor"]

# Pemetaan label mapel saat DITAMPILKAN (nama kolom di Excel tidak diubah)
SUBJECT_DISPLAY_ALIASES = {
    "bhs": "Bahasa Indonesia",
    "ind": "Bahasa Indonesia",
    "b indonesia": "Bahasa Indonesia",
    "b. indonesia": "Bahasa Indonesia",
    "mat": "Matematika",
    "mtk": "Matematika",
    "matematika": "Matematika",
}


def _canon(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower().replace("_", " "))


def pretty_subject(col_name: str) -> str:
    """Ubah label kolom jadi nama mapel yang cantik untuk tampilan."""
    key = _canon(col_name)
    return SUBJECT_DISPLAY_ALIASES.get(key, col_name)


def pick_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    colset = {_canon(c): c for c in cols}
    # exact match lebih dulu
    for cand in candidates:
        key = _canon(cand)
        if key in colset:
            return colset[key]
    # fuzzy fallback
    choices = list(colset.keys())
    if not choices:
        return None
    best_key, best_score = None, -1
    for cand in candidates:
        m = process.extractOne(_canon(cand), choices, scorer=fuzz.QRatio)
        if m and m[1] > best_score:
            best_key, best_score = m[0], m[1]
    if best_score >= 80 and best_key is not None:
        return colset[best_key]
    return None


def _strip_accents(txt: str) -> str:
    norm = unicodedata.normalize("NFKD", str(txt))
    return "".join(c for c in norm if not unicodedata.combining(c))


def _norm_name(txt: str) -> str:
    t = _strip_accents(str(txt))
    t = re.sub(r"\s+", " ", t).strip()
    return t.casefold()  # lebih kuat daripada lower()


@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, engine="openpyxl")
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip()
    return df


def infer_schema(df: pd.DataFrame) -> Tuple[str, Optional[str], Optional[str], List[str]]:
    cols = list(df.columns)
    name_col = pick_col(cols, NAME_CANDS)
    no_col = pick_col(cols, NO_CANDS)
    final_col = pick_col(cols, FINAL_CANDS)

    # kolom nilai numerik
    numeric_cols = []
    for c in cols:
        if c in {name_col, no_col, final_col}:
            continue
        series = pd.to_numeric(df[c], errors="coerce")
        if series.notna().mean() >= 0.6:
            numeric_cols.append(c)

    if not name_col:
        raise ValueError(
            "Kolom nama tidak ditemukan. Pastikan salah satu ada: " + ", ".join(NAME_CANDS)
        )
    if not final_col and not numeric_cols:
        raise ValueError(
            "Tidak menemukan 'Skor Akhir' dan tidak ada kolom numerik untuk dihitung."
        )
    return name_col, no_col, final_col, numeric_cols


def compute_final_and_rank(
    df: pd.DataFrame, name_col: str, final_col: Optional[str], subject_cols: List[str]
) -> pd.DataFrame:
    work = df.copy()

    # 1) hitung skor akhir (float)
    if final_col:
        work["_final_float"] = pd.to_numeric(work[final_col], errors="coerce")
    else:
        for c in subject_cols:
            work[c] = pd.to_numeric(work[c], errors="coerce")
        work["_final_float"] = work[subject_cols].mean(axis=1, skipna=True)

    work["_final_float"] = work["_final_float"].fillna(0)

    # 2) skor akhir pembulatan (dipakai untuk tampilan & ranking)
    work["_final_round"] = work["_final_float"].round(0).astype(int)

    # 3) ranking dengan dense rank BERDASAR skor bulat → skor sama = peringkat sama
    work["_rank"] = work["_final_round"].rank(method="dense", ascending=False).astype(int)

    return work


def label_predikat(n: float) -> str:
    if n >= 90:
        return "Istimewa"
    if n >= 85:
        return "Sangat Baik"
    if n >= 75:
        return "Baik"
    if n >= 65:
        return "Cukup"
    return "Perlu Bimbingan"


def exact_match(df: pd.DataFrame, name_col: str, nama_input: str) -> pd.DataFrame:
    """Full-match nama TAPI case-insensitive via kolom _name_norm."""
    key = _norm_name(nama_input)
    if "_name_norm" in df.columns:
        return df[df["_name_norm"] == key]
    return df[df[name_col].astype(str).map(_norm_name) == key]


def leaderboard_groups(df: pd.DataFrame, name_col: str, max_unique_ranks: int = 3):
    """
    Kembalikan list berisi grup peringkat:
    [{'rank': 1, 'score': 95, 'rows': DataFrame_nama2}, ...]
    Menggunakan skor bulat sehingga skor sama → satu peringkat.
    """
    temp = df[[name_col, "_final_round"]].copy()
    temp = temp.sort_values(by=["_final_round", name_col], ascending=[False, True])
    groups = []
    current_rank = 1
    for score, g in temp.groupby("_final_round", sort=False):
        groups.append({"rank": current_rank, "score": int(score), "rows": g})
        current_rank += 1
        if len(groups) >= max_unique_ranks:
            break
    return groups


# =================== DARK THEME + MODERN UI ===================
st.markdown(
    """
    <style>
      :root{
        --bg:#0b1324;
        --panel:#0f172a;
        --panel-2:#0c152b;
        --border:#1f2b3f;
        --ink:#f8fafc;
        --muted:#cbd5e1;
        --brand:#38bdf8;
        --gradA:#2dd4bf;
        --gradB:#60a5fa;
        --okA:#22c55e;
        --okB:#16a34a;
      }

      html, body, .stApp { background: radial-gradient(1200px 600px at 10% -10%, #13243d 0%, var(--bg) 40%); color: var(--ink); }
      #MainMenu, header, footer { visibility: hidden; }
      .block-container{ padding-top:1.6rem; max-width:980px; }

      h1,h2,h3,h4,h5,h6, p, li, label, .stMarkdown { color: var(--ink) !important; }
      a { color: var(--brand) !important; text-decoration: none; }

      [data-baseweb="input"] input{
        background: #0c1426 !important;
        color: var(--ink) !important;
        border: 1px solid var(--border) !important;
        border-radius: 14px !important;
      }
      .stButton > button{
        width: 100%;
        border-radius: 12px;
        padding: .7rem 1rem;
        border: 1px solid #1f2b3f;
        background: linear-gradient(135deg,#1e293b,#0f172a);
        color: var(--ink);
        box-shadow: 0 6px 20px rgba(2,6,23,.35);
      }
      .stButton > button:hover{
        transform: translateY(-1px);
        border-color:#334155;
      }

      .card, .card-plain{
        border-radius: 18px;
        border: 1px solid var(--border);
        background: linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.00));
        padding: 18px 20px;
        box-shadow: 0 12px 40px rgba(2, 6, 23, .35), inset 0 1px 0 rgba(255,255,255,.04);
        margin: 12px 0;
      }
      .card-plain{ background: #0c152b; }

      .hero{ display:flex; gap:14px; align-items:center; margin:0 0 10px 0; }
      .hero-icon{
        width:48px; height:48px; border-radius:14px;
        background: conic-gradient(from 210deg, var(--gradA), var(--gradB), #a78bfa, var(--gradA));
        display:flex; align-items:center; justify-content:center;
        font-size:24px; color:#001018; box-shadow: 0 10px 28px rgba(56,189,248,.28);
      }
      .subtitle{ color: var(--muted); font-size:14px; margin-top:-2px; }

      .metric-wrap{
        position: relative;
        border-radius: 18px;
        padding: 0;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,.08);
        background: linear-gradient(135deg, rgba(34,197,94,.18), rgba(21,128,61,.18));
      }
      .metric{
        border-radius: 18px;
        padding: 18px;
        color:#fff; text-align:center; font-weight:800; font-size:28px;
        background: linear-gradient(135deg, var(--okA), var(--okB));
        box-shadow: 0 12px 36px rgba(16,185,129,.35);
      }
      .chip{
        display:inline-block; padding:4px 10px; border-radius:999px;
        background: rgba(255,255,255,.12); color:#fff; border:1px solid rgba(255,255,255,.25);
        font-size:12px; margin-left:8px;
      }

      .grid{ display:grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap:12px; }
      @media (max-width: 640px){ .grid{ grid-template-columns:1fr; } }
      .pill{
        background: linear-gradient(180deg, #0f1a31, #0b1528);
        border:1px solid var(--border); border-radius:14px;
        padding:12px 14px; display:flex; justify-content:space-between; align-items:center;
        font-weight:700; color:var(--ink);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
      }
      .pill span{ font-weight:500; color:var(--muted); }

      .lb{ display:flex; flex-direction:column; gap:10px; }
      .lb-rank{ font-weight:800; color:#e5e7eb; margin-top:6px; }
      .lb-item{ display:flex; align-items:center; gap:10px; padding:6px 0; color:var(--ink); }
      .lb-name{ font-weight:700; letter-spacing:.2px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============== HEADER (HERO) ==============
st.markdown(
    """
    <div class="hero">
      <div class="hero-icon">📊</div>
      <div>
        <h1 style="margin:0;">Pengumuman Hasil Try Out - SMPN 1 Sooko Mojokerto</h1>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# =================== LOAD DATA SEKALI ===================
try:
    df_raw = load_data(DATA_PATH)
    name_col, no_col, final_col, subject_cols = infer_schema(df_raw)
    df = compute_final_and_rank(df_raw, name_col, final_col, subject_cols)
    total_peserta = len(df)
    # kolom normalisasi nama untuk pencarian case-insensitive
    df["_name_norm"] = df[name_col].astype(str).map(_norm_name)
except Exception as e:
    st.error(f"Gagal memuat data: {e}")
    st.stop()

# =================== ROUTING ===================
def goto_result(nama: str):
    for k in list(st.session_state.keys()):
        if k.startswith("search_"):
            st.session_state.pop(k, None)
    st.query_params.from_dict({"view": "result", "q": nama})
    st.rerun()


def goto_search():
    st.query_params.clear()
    st.rerun()


def card_html(title: str, body_html: str, plain: bool = False) -> str:
    klass = "card-plain" if plain else "card"
    return f"""
      <div class="{klass}">
        <h3 style="margin:0 0 10px 0;">{title}</h3>
        {body_html}
      </div>
    """


# ============== PAGE: SEARCH ==============
def page_search():
    st.markdown(
        card_html(
            "Cari Nama Peserta",
            '<div style="height:6px;"></div>',
            plain=True,
        ),
        unsafe_allow_html=True,
    )

    with st.form("search_form", clear_on_submit=False):
        nama = st.text_input(
            "Nama Lengkap",
            placeholder="Silakan ketik nama lengkap anda",
            key="search_name",
            label_visibility="visible",
        )
        submitted = st.form_submit_button("Tampilkan Hasil")

    if st.session_state.get("search_error"):
        st.warning(st.session_state["search_error"])
        st.session_state["search_error"] = ""

    if submitted:
        nama = (nama or "").strip()
        if not nama:
            st.session_state["search_error"] = "Nama belum diisi."
        else:
            exists = df["_name_norm"].eq(_norm_name(nama)).any()
            if not exists:
                st.session_state["search_error"] = (
                    "Nama tidak ada di data. Cek ejaan ya (huruf besar/kecil tidak berpengaruh)."
                )
            else:
                st.session_state["search_error"] = ""
                goto_result(nama)
        st.rerun()


# ============== PAGE: RESULT ==============
def page_result(nama_param: str):
    df_hit = exact_match(df, name_col, nama_param.strip())
    if df_hit.empty:
        st.warning("Nama tidak ada di data. Cek ejaan (huruf besar/kecil bebas).")
        st.button("← Kembali", on_click=goto_search, use_container_width=True)
        return

    # Duplikat nama → pilih berdasarkan No Urut (jika ada)
    if len(df_hit) > 1 and no_col:
        st.markdown(
            card_html(
                "Nama Ganda Ditemukan",
                "<p>Pilih Nomor Urut yang benar:</p>",
                plain=True,
            ),
            unsafe_allow_html=True,
        )
        options = (
            df_hit[[name_col, no_col]]
            .astype(str)
            .apply(lambda r: f"{r[name_col]} (No Urut {r[no_col]})", axis=1)
            .tolist()
        )
        pilihan = st.selectbox("Pilih peserta", options, index=0)
        m = re.search(r"No Urut\s(.+?)\)$", pilihan)
        chosen_no = m.group(1) if m else None
        if chosen_no is not None:
            df_hit = df_hit[df_hit[no_col].astype(str) == str(chosen_no)]

    row = df_hit.iloc[0]

    # Tombol kembali
    st.button("← Kembali", on_click=goto_search, use_container_width=True)

    # ===== IDENTITAS & PERINGKAT =====
    ident_body = (
        f"<p style='margin:.3rem 0 0;'>Selamat datang, <b>{row[name_col]}</b></p>"
        + (f"<p style='margin:.1rem 0 0;'><b>Nomor Urut</b>: {row[no_col]}</p>" if no_col else "")
        + f"<div style='margin-top:.6rem;'><span class='chip'>Peringkat {int(row['_rank'])} dari {total_peserta}</span></div>"
    )
    st.markdown(card_html("Hasil Try Out", ident_body), unsafe_allow_html=True)

    # ===== METRIC SKOR =====
    skor = int(row["_final_round"])
    metric_html = (
        "<div class='metric-wrap'>"
        "<div class='metric'>"
        f"Skor Akhir: {skor}"
        f"<span class='chip'>{label_predikat(skor)}</span>"
        "</div>"
        "</div>"
    )
    st.markdown(metric_html, unsafe_allow_html=True)

    # ===== NILAI PER MAPEL (GRID) =====
    items = []
    for c in sorted(subject_cols):
        v = pd.to_numeric(row[c], errors="coerce")
        if pd.notna(v):
            label = pretty_subject(c)  # <<— tampilkan label mapel cantik
            items.append(f"<div class='pill'><span>{label}</span> {int(round(v))}</div>")
    if items:
        grid_html = "<div class='grid'>" + "".join(items) + "</div>"
    else:
        grid_html = (
            "<div class='grid'><div class='pill'><span>Tidak ada data nilai per mapel</span> -</div></div>"
        )
    st.markdown(card_html("Hasil Nilai", grid_html), unsafe_allow_html=True)

    # ===== LEADERBOARD =====
    groups = leaderboard_groups(df, name_col, max_unique_ranks=3)
    medal_map = {1: "🥇", 2: "🥈", 3: "🥉"}
    lb_parts = []
    for g in groups:
        header = f"<div class='lb-rank'>{medal_map.get(g['rank'], '🏅')} Peringkat {g['rank']} — Skor {g['score']}</div>"
        names_html = "".join(
            [f"<div class='lb-item'><span class='lb-name'>{r[name_col]}</span></div>" for _, r in g["rows"].iterrows()]
        )
        lb_parts.append(header + names_html)
    lb_html = "<div class='lb'>" + "".join(lb_parts) + "</div>"
    st.markdown(card_html("Peringkat Teratas", lb_html), unsafe_allow_html=True)


# ===== Render route =====
view = st.query_params.get("view", "search")
q = st.query_params.get("q", "")
if view == "result" and q:
    page_result(q)
else:
    page_search()