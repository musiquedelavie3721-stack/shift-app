import streamlit as st
import pandas as pd
import random
import calendar
import time
from datetime import date

# --- Constants ---
SHIFT_EARLY = '早'
SHIFT_DAY = '日'
SHIFT_LATE = '遅'
SHIFT_NIGHT = '夜'
SHIFT_DAWN = '明'
SHIFT_OFF = '公'
SHIFT_PAID = '有'

DEFAULT_HEADCOUNT = {
    SHIFT_EARLY: 2,
    SHIFT_DAY: 1,
    SHIFT_LATE: 2,
    SHIFT_NIGHT: 1
}

MAX_CONSECUTIVE_WORK_DAYS = 3
MONTHLY_PUBLIC_OFF_DAYS = 9
MAX_NIGHT_SHIFTS = 6
MAX_DAY_SHIFTS = 2

ALL_SHIFTS = [SHIFT_EARLY, SHIFT_DAY, SHIFT_LATE, SHIFT_NIGHT]
NO_NIGHT_SHIFTS = [SHIFT_EARLY, SHIFT_DAY, SHIFT_LATE]

# --- Logic Class ---

class ScheduleGenerator:
    def __init__(self, config):
        self.year = config['year']
        self.month = config['month']
        self.staff_list = config['staff_list']
        self.headcount = config.get('headcount', DEFAULT_HEADCOUNT)
        self.days_in_month = calendar.monthrange(self.year, self.month)[1]
        self.days = list(range(1, self.days_in_month + 1))

    def is_work_shift(self, shift):
        return shift in [SHIFT_EARLY, SHIFT_DAY, SHIFT_LATE, SHIFT_NIGHT, SHIFT_DAWN]

    def shuffle_list(self, lst):
        random.shuffle(lst)

    def generate(self):
        # Best of N Approach
        max_retries = 500
        best_schedule = None
        min_deficit = float('inf')

        for attempt in range(max_retries):
            schedule = {staff['id']: [None] * (self.days_in_month + 1) for staff in self.staff_list}
            
            # 1. Pre-fill Requests
            for staff in self.staff_list:
                requests = staff.get('requests', {})
                for day_str, shift in requests.items():
                    day = int(day_str)
                    schedule[staff['id']][day] = shift
                    if shift == SHIFT_NIGHT:
                        if day + 1 <= self.days_in_month:
                            schedule[staff['id']][day + 1] = SHIFT_DAWN
                        if day + 2 <= self.days_in_month:
                             # Only set if not already set (though request priority should handle it, logic implies strictly OFF after Dawn)
                             # In JS: schedule[staff.id][day + 2] = C.SHIFT_OFF;
                             schedule[staff['id']][day + 2] = SHIFT_OFF

            current_deficit = 0

            for day in self.days:
                # Count assigned
                assigned_counts = {k: 0 for k in self.headcount}
                for staff in self.staff_list:
                    s = schedule[staff['id']][day]
                    if s in assigned_counts:
                        assigned_counts[s] += 1
                
                # Needs
                needs = []
                for shift, count in self.headcount.items():
                    needed = count - assigned_counts[shift]
                    if needed > 0:
                        needs.extend([shift] * needed)
                
                needs.sort(key=lambda x: 0 if x == SHIFT_NIGHT else 1)

                # Available Staff
                available_staff_ids = [s['id'] for s in self.staff_list if schedule[s['id']][day] is None]

                # Check previous day sequences (Dawn/Night logic)
                true_available = []
                for sid in available_staff_ids:
                    prev_shift = schedule[sid][day - 1] if day > 1 else None
                    
                    if prev_shift == SHIFT_NIGHT:
                         schedule[sid][day] = SHIFT_DAWN
                    elif prev_shift == SHIFT_DAWN:
                         schedule[sid][day] = SHIFT_OFF
                    else:
                        true_available.append(sid)
                
                available_staff_ids = true_available
                self.shuffle_list(available_staff_ids)

                # Capacity Ratio
                est_max_shifts = self.days_in_month - MONTHLY_PUBLIC_OFF_DAYS
                total_capacity = len(self.staff_list) * est_max_shifts
                total_required = sum(self.headcount.values()) * self.days_in_month
                
                # JS Logic: const capacityRatio = Math.min(1.0, totalCapacity / totalRequired);
                # Used later for specific shifts

                for shift_type in needs:
                    # Sort candidates
                    def count_shifts(sid):
                        c = 0
                        for d in range(1, self.days_in_month + 1):
                            if schedule[sid][d] == shift_type:
                                c += 1
                        return c
                    
                    available_staff_ids.sort(key=count_shifts)

                    # Probabilistic Skip
                    if shift_type in [SHIFT_DAY, SHIFT_NIGHT]:
                        max_shifts = MAX_NIGHT_SHIFTS if shift_type == SHIFT_NIGHT else MAX_DAY_SHIFTS
                        
                        remaining_capacity = 0
                        for s in self.staff_list:
                            if not s.get('allowed_shifts') or shift_type in s.get('allowed_shifts', []):
                                assigned_so_far = sum(1 for d in range(1, self.days_in_month + 1) if schedule[s['id']][d] == shift_type)
                                remaining_capacity += max(0, max_shifts - assigned_so_far)
                        
                        remaining_days = self.days_in_month - day + 1
                        remaining_demand = remaining_days * self.headcount[shift_type]
                        
                        dynamic_ratio = 1.0
                        if remaining_demand > 0:
                            dynamic_ratio = remaining_capacity / remaining_demand
                            if dynamic_ratio > 1.0: dynamic_ratio = 1.0
                        
                        if dynamic_ratio < 1.0:
                            if random.random() > dynamic_ratio:
                                current_deficit += 1
                                continue

                    assigned_to = None
                    best_candidate_idx = -1
                    fallback_candidate_idx = -1

                    for i, sid in enumerate(available_staff_ids):
                        staff = next(s for s in self.staff_list if s['id'] == sid)

                        # Allowed check
                        if staff.get('allowed_shifts') and shift_type not in staff['allowed_shifts']:
                            continue
                        
                        # Max Consecutive
                        streak = 0
                        for k in range(1, 6):
                            if day - k < 1: break
                            if self.is_work_shift(schedule[sid][day - k]):
                                streak += 1
                            else:
                                break
                        
                        if shift_type != SHIFT_NIGHT:
                            if streak >= MAX_CONSECUTIVE_WORK_DAYS: continue
                        
                        if shift_type == SHIFT_DAY:
                            # No consecutive Day
                            if day > 1 and schedule[sid][day - 1] == SHIFT_DAY: continue
                            
                            day_count = sum(1 for d in range(1, self.days_in_month + 1) if schedule[sid][d] == SHIFT_DAY)
                            if day_count >= MAX_DAY_SHIFTS: continue

                        if shift_type == SHIFT_NIGHT:
                            if streak > MAX_CONSECUTIVE_WORK_DAYS: continue # >3 allowed if Night
                            
                            night_count = sum(1 for d in range(1, self.days_in_month + 1) if schedule[sid][d] == SHIFT_NIGHT)
                            if night_count >= MAX_NIGHT_SHIFTS: continue

                            if day + 1 <= self.days_in_month and schedule[sid][day + 1] is not None:
                                continue
                        
                        # Soft Constraint: Late -> Early
                        prev_shift = schedule[sid][day - 1] if day > 1 else None
                        if shift_type == SHIFT_EARLY and prev_shift == SHIFT_LATE:
                            if fallback_candidate_idx == -1:
                                fallback_candidate_idx = i
                            continue
                        
                        best_candidate_idx = i
                        break
                    
                    final_idx = -1
                    if best_candidate_idx != -1:
                        final_idx = best_candidate_idx
                    elif fallback_candidate_idx != -1:
                        final_idx = fallback_candidate_idx
                    
                    if final_idx != -1:
                        sid = available_staff_ids[final_idx]
                        schedule[sid][day] = shift_type
                        
                        if shift_type == SHIFT_NIGHT:
                            if day + 1 <= self.days_in_month:
                                schedule[sid][day + 1] = SHIFT_DAWN
                            if day + 2 <= self.days_in_month and schedule[sid][day + 2] is None:
                                schedule[sid][day + 2] = SHIFT_OFF
                        
                        available_staff_ids.pop(final_idx)
                        assigned_to = sid
                    
                    if not assigned_to:
                        current_deficit += 1
                        continue
                
                # Fill rest with OFF
                for sid in available_staff_ids:
                    schedule[sid][day] = SHIFT_OFF
            
            if current_deficit == 0:
                return self.finalize_schedule(schedule)
            
            if current_deficit < min_deficit:
                min_deficit = current_deficit
                best_schedule = schedule
        
        if best_schedule:
            print(f"Best schedule found with deficit: {min_deficit}")
            return self.finalize_schedule(best_schedule)
        
        return {'success': False}

    def finalize_schedule(self, schedule):
        # Enforce 9 Public Holidays
        for staff in self.staff_list:
            sid = staff['id']
            off_days_indices = []
            requests = staff.get('requests', {})
            
            for d in range(1, self.days_in_month + 1):
                if schedule[sid][d] == SHIFT_OFF:
                    # Check if requested
                    if str(d) in requests and requests[str(d)] == SHIFT_OFF:
                        pass
                    else:
                        off_days_indices.append(d)
            
            current_off_count = sum(1 for d in range(1, self.days_in_month + 1) if schedule[sid][d] == SHIFT_OFF)

            # Case 1: Too many holidays
            if current_off_count > MONTHLY_PUBLIC_OFF_DAYS:
                excess = current_off_count - MONTHLY_PUBLIC_OFF_DAYS
                self.shuffle_list(off_days_indices)
                
                removed = 0
                
                # Pass 1: Fill Shortages
                for k in range(len(off_days_indices)):
                    if removed >= excess: break
                    d_idx = off_days_indices[k]
                    
                    cE, cD, cL = 0, 0, 0
                    for s in self.staff_list:
                         sh = schedule[s['id']][d_idx]
                         if sh == SHIFT_EARLY: cE += 1
                         if sh == SHIFT_DAY: cD += 1
                         if sh == SHIFT_LATE: cL += 1
                    
                    needE = cE < self.headcount[SHIFT_EARLY]
                    needD = cD < self.headcount[SHIFT_DAY]
                    needL = cL < self.headcount[SHIFT_LATE]

                    prev_shift = schedule[sid][d_idx - 1] if d_idx > 1 else None

                    target_shift = None
                    allowed = staff.get('allowed_shifts', [])

                    if needD and (not allowed or SHIFT_DAY in allowed) and prev_shift != SHIFT_DAY:
                        target_shift = SHIFT_DAY
                    elif needE and (not allowed or SHIFT_EARLY in allowed):
                         target_shift = SHIFT_EARLY
                    elif needL and (not allowed or SHIFT_LATE in allowed):
                         target_shift = SHIFT_LATE
                    
                    if target_shift:
                        schedule[sid][d_idx] = target_shift
                        removed += 1
                        off_days_indices[k] = -1
                
                # Pass 2: Overfill
                if removed < excess:
                    for k in range(len(off_days_indices)):
                        if removed >= excess: break
                        d_idx = off_days_indices[k]
                        if d_idx == -1: continue
                        
                        prev_shift = schedule[sid][d_idx - 1] if d_idx > 1 else None
                        target_shift = None
                        allowed = staff.get('allowed_shifts', [])

                        if (not allowed or SHIFT_DAY in allowed) and prev_shift != SHIFT_DAY:
                            target_shift = SHIFT_DAY
                        elif (not allowed or SHIFT_EARLY in allowed):
                            target_shift = SHIFT_EARLY
                        elif (not allowed or SHIFT_LATE in allowed):
                            target_shift = SHIFT_LATE
                        
                        if target_shift:
                            schedule[sid][d_idx] = target_shift
                            removed += 1
            
            # Case 2: Not enough holidays
            elif current_off_count < MONTHLY_PUBLIC_OFF_DAYS:
                deficit = MONTHLY_PUBLIC_OFF_DAYS - current_off_count
                work_indices = []
                for d in range(1, self.days_in_month + 1):
                    if str(d) in requests: continue
                    s = schedule[sid][d]
                    if s in [SHIFT_EARLY, SHIFT_DAY, SHIFT_LATE]:
                        work_indices.append(d)
                
                self.shuffle_list(work_indices)
                added = 0
                for k in range(len(work_indices)):
                    if added >= deficit: break
                    schedule[sid][work_indices[k]] = SHIFT_OFF
                    added += 1

            # --- Enforce 2 DAY Shifts ---
            allowed = staff.get('allowed_shifts', [])
            if not allowed or SHIFT_DAY in allowed:
                day_indices = []
                for d in range(1, self.days_in_month + 1):
                    if schedule[sid][d] == SHIFT_DAY:
                        if not (str(d) in requests and requests[str(d)] == SHIFT_DAY):
                            day_indices.append(d)
                
                current_day_count = sum(1 for d in range(1, self.days_in_month + 1) if schedule[sid][d] == SHIFT_DAY)

                if current_day_count > MAX_DAY_SHIFTS:
                    excess = current_day_count - MAX_DAY_SHIFTS
                    self.shuffle_list(day_indices)
                    changed = 0
                    for k in range(len(day_indices)):
                        if changed >= excess: break
                        d = day_indices[k]
                        prev_shift = schedule[sid][d - 1] if d > 1 else None
                        
                        target = None
                        if (not allowed or SHIFT_EARLY in allowed) and prev_shift != SHIFT_LATE:
                            target = SHIFT_EARLY
                        elif (not allowed or SHIFT_LATE in allowed):
                             target = SHIFT_LATE
                        elif (not allowed or SHIFT_EARLY in allowed):
                             target = SHIFT_EARLY
                        
                        if target:
                            schedule[sid][d] = target
                            changed += 1
                
                elif current_day_count < MAX_DAY_SHIFTS:
                    deficit = MAX_DAY_SHIFTS - current_day_count
                    candidates = []
                    for d in range(1, self.days_in_month + 1):
                        if str(d) in requests: continue
                        s = schedule[sid][d]
                        if s in [SHIFT_EARLY, SHIFT_LATE]:
                            candidates.append(d)
                    
                    self.shuffle_list(candidates)
                    changed = 0
                    for k in range(len(candidates)):
                         if changed >= deficit: break
                         d = candidates[k]
                         curr = schedule[sid][d]

                         # Critical Headcount Check
                         type_count = 0
                         for s in self.staff_list:
                             if schedule[s['id']][d] == curr: type_count += 1
                        
                         if type_count <= self.headcount[curr]: continue

                         prev_shift = schedule[sid][d - 1] if d > 1 else None
                         next_shift = schedule[sid][d + 1] if d < self.days_in_month else None
                         if prev_shift == SHIFT_DAY or next_shift == SHIFT_DAY: continue
                         
                         schedule[sid][d] = SHIFT_DAY
                         changed += 1

        # --- Post Processing: Early/Late 2 per day ---
        for day in range(1, self.days_in_month + 1):
            early_count = 0
            late_count = 0
            day_staff_ids = []

            for s in self.staff_list:
                sh = schedule[s['id']][day]
                if sh == SHIFT_EARLY: early_count += 1
                if sh == SHIFT_LATE: late_count += 1
                if sh == SHIFT_DAY:
                     req = s.get('requests', {})
                     if not (str(day) in req and req[str(day)] == SHIFT_DAY):
                         day_staff_ids.append(s['id'])
            
            # Fill Early
            while early_count < self.headcount[SHIFT_EARLY] and day_staff_ids:
                sid = day_staff_ids.pop()
                staff = next(s for s in self.staff_list if s['id'] == sid)
                allowed = staff.get('allowed_shifts', [])
                if not allowed or SHIFT_EARLY in allowed:
                    schedule[sid][day] = SHIFT_EARLY
                    early_count += 1
            
             # Recount Day staff
            day_staff_ids = []
            for s in self.staff_list:
                sh = schedule[s['id']][day]
                if sh == SHIFT_DAY:
                     req = s.get('requests', {})
                     if not (str(day) in req and req[str(day)] == SHIFT_DAY):
                         day_staff_ids.append(s['id'])

            # Fill Late
            while late_count < self.headcount[SHIFT_LATE] and day_staff_ids:
                sid = day_staff_ids.pop()
                staff = next(s for s in self.staff_list if s['id'] == sid)
                allowed = staff.get('allowed_shifts', [])
                if not allowed or SHIFT_LATE in allowed:
                    schedule[sid][day] = SHIFT_LATE
                    late_count += 1

        return {'success': True, 'schedule': schedule, 'days': self.days}

# --- Streamlit UI ---

st.set_page_config(page_title="勤務表自動作成", layout="wide")

# Custom CSS for styling
st.markdown("""
<style>
    /* Hide the selectbox icon in data_editor column headers */
    [data-testid="stDataFrameResizable"] th svg {
        display: none !important;
    }
    [data-testid="column-header-icon"] {
        display: none !important;
    }
    /* Minimize top padding */
    .block-container {
        padding-top: 2rem;
    }
    /* Sidebar styling adjustments */
    [data-testid="stSidebar"] .stButton button {
        width: 100%;
        text-align: left;
    }
</style>
""", unsafe_allow_html=True)

# Init Session State
if 'staff_list' not in st.session_state:
    st.session_state.staff_list = [
        {'id': 1, 'name': "神田", 'allowed_shifts': NO_NIGHT_SHIFTS, 'requests': {}},
        {'id': 2, 'name': "山崎", 'allowed_shifts': NO_NIGHT_SHIFTS, 'requests': {}},
        {'id': 3, 'name': "熊澤", 'allowed_shifts': NO_NIGHT_SHIFTS, 'requests': {}},
        {'id': 4, 'name': "長谷川", 'allowed_shifts': NO_NIGHT_SHIFTS, 'requests': {}},
        {'id': 5, 'name': "尾川", 'allowed_shifts': NO_NIGHT_SHIFTS, 'requests': {}},
        {'id': 6, 'name': "上原", 'allowed_shifts': ALL_SHIFTS, 'requests': {}},
        {'id': 7, 'name': "冨田", 'allowed_shifts': ALL_SHIFTS, 'requests': {}},
        {'id': 8, 'name': "松田", 'allowed_shifts': ALL_SHIFTS, 'requests': {}},
        {'id': 9, 'name': "秋本", 'allowed_shifts': ALL_SHIFTS, 'requests': {}}
    ]

if 'generated_schedule' not in st.session_state:
    st.session_state.generated_schedule = None

# Sidebar
with st.sidebar:
    st.title("勤務表自動作成")
    
    st.header("期間設定")
    col_y, col_m = st.columns([1, 1])
    year = col_y.number_input("年", value=2026, step=1, label_visibility="collapsed")
    month = col_m.selectbox("月", range(1, 13), index=1, label_visibility="collapsed") # Default Feb
    
    # Update days based on sidebar input
    days_in_month = calendar.monthrange(year, month)[1]
    days = list(range(1, days_in_month + 1))

    st.header("スタッフ管理")
    
    # Staff List - Compact View
    for i, staff in enumerate(st.session_state.staff_list):
        c1, c2 = st.columns([3, 1])
        with c1:
            with st.expander(f"{staff['name']}", expanded=False):
                # Shift Config
                allowed = st.multiselect(
                    "可能シフト", 
                    ALL_SHIFTS, 
                    default=staff['allowed_shifts'],
                    key=f"allow_{staff['id']}"
                )
                staff['allowed_shifts'] = allowed
        with c2:
             if st.button("✕", key=f"del_{staff['id']}", help="削除"):
                st.session_state.staff_list.pop(i)
                st.rerun()

    new_name = st.text_input("新規スタッフ名", placeholder="名前を入力")
    if st.button("スタッフ追加"):
        if new_name:
            st.session_state.staff_list.append({
                'id': int(time.time() * 1000),
                'name': new_name,
                'allowed_shifts': ALL_SHIFTS.copy(),
                'requests': {}
            })
            st.rerun()

    st.markdown("---")
    st.header("アクション")
    if st.button("勤務表を作成", type="primary"):
        config = {
            'year': year,
            'month': month,
            'staff_list': st.session_state.staff_list
        }
        with st.spinner("生成中..."):
            generator = ScheduleGenerator(config)
            result = generator.generate()
            if result['success']:
                st.session_state.generated_schedule = result['schedule']
                st.success("作成完了！")
            else:
                st.error("作成失敗：条件を満たすシフトが見つかりませんでした。")
    
    if st.session_state.generated_schedule:
        if st.button("リセット"):
            st.session_state.generated_schedule = None
            st.rerun()

# --- Main Area ---

st.subheader("希望休・シフト入力")
st.caption("セルをクリックしてシフトを選択してください。入力後「勤務表を作成」で生成します。")

# Build DataFrame for editing (Requests mode)
if st.session_state.generated_schedule is None:
    # Show editable request table
    data = {}
    
    # Pre-populate data with sanitized values
    for d in days:
        col_data = []
        for staff in st.session_state.staff_list:
            val = staff['requests'].get(str(d), "")
            # Strict sanitization
            if val is None or str(val) == "None":
                val = ""
            col_data.append(val)
        data[str(d)] = col_data
    
    # Create DF with "氏名" as index
    staff_names = [s['name'] for s in st.session_state.staff_list]
    df_edit = pd.DataFrame(data, index=staff_names)
    
    # Column config for dropdown
    shift_options = ["", SHIFT_OFF, SHIFT_PAID, SHIFT_EARLY, SHIFT_DAY, SHIFT_LATE, SHIFT_NIGHT]
    
    column_config = {
        "_index": st.column_config.Column("氏名", disabled=True, width="small")
    }
    for d in days:
        column_config[str(d)] = st.column_config.SelectboxColumn(
            str(d),
            options=shift_options,
            default="",
            required=False,
            width="small"
        )
    
    edited_df = st.data_editor(
        df_edit,
        column_config=column_config,
        use_container_width=True,
        key="request_editor",
        num_rows="fixed"
    )
    
    # Sync edits back to session state
    for i, name in enumerate(staff_names):
        # Find staff by name (index) - assuming unique names or using index mapping
        staff = st.session_state.staff_list[i]
        new_requests = {}
        for d in days:
            val = edited_df.iloc[i][str(d)]
            if val is not None and str(val) != "" and str(val) != "None":
                new_requests[str(d)] = val
        staff['requests'] = new_requests

else:
    # Generated schedule view (read-only)
    st.subheader("勤務表（生成済み）")
    
    data = []
    headers = [str(d) for d in days]
    
    for staff in st.session_state.staff_list:
        row = [staff['name']]
        for d in days:
            val = st.session_state.generated_schedule[staff['id']][d]
            row.append(val if val else "")
        data.append(row)
    
    df = pd.DataFrame(data, columns=["氏名"] + headers)
    st.dataframe(df, use_container_width=True)

    # Help Needed Row
    st.caption("不足人員")
    help_row = []
    
    for d in days:
        cnt_day = 0
        cnt_night = 0
        for staff in st.session_state.staff_list:
             s = st.session_state.generated_schedule[staff['id']][d]
             if s == SHIFT_DAY: cnt_day += 1
             if s == SHIFT_NIGHT: cnt_night += 1
        
        alerts = []
        if cnt_day < DEFAULT_HEADCOUNT[SHIFT_DAY]: alerts.append("日")
        if cnt_night < DEFAULT_HEADCOUNT[SHIFT_NIGHT]: alerts.append("夜")
        
        help_row.append("/".join(alerts) if alerts else "")

    df_help = pd.DataFrame([help_row], columns=headers, index=["不足"])
    st.dataframe(df_help, use_container_width=True)

    # CSV Download
    csv = df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        "CSVダウンロード",
        csv,
        f"schedule_{year}_{month}.csv",
        "text/csv",
        key='download-csv',
        type="primary"
    )
