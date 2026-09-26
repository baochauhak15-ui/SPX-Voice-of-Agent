# -*- coding: utf-8 -*-
"""
Synthetic SPX Voice-of-Operations data generator.

Everything here is FAKE: IDs, hubs, comments, parcels. No production data, no PII.
Deterministic for a given --seed.

Embedded demo stories (see ARCHITECTURE_SPX.md §3.1):
  A (main) HCM-ThuDuc-SOC hub processing delay from 2026-09-14 → Customer + Seller + Rider VOC ↑,
           ops sort_complete processing_time ↑ at that hub (starts 1 day earlier).
  B        Seller "failed delivery after 2 attempts — what next?" + Help Center article that does
           not explain the next step → knowledge gap.
  C        Seller COD / settlement complaints, flat → should stay P3 monitor.
  D        Rider app login issue, small spike in HN-LongBien → single-stakeholder, Product owner.
"""
import argparse
import csv
import os
import random
import unicodedata
from datetime import date, datetime, timedelta

START = date(2026, 7, 27)
END = date(2026, 9, 20)                 # inclusive, 8 weeks
INCIDENT_START = date(2026, 9, 14)
OPS_DEGRADE_START = date(2026, 9, 13)   # ops deteriorates one day before VOC spikes
INCIDENT_HUB = "HCM-ThuDuc-SOC"
APP_SPIKE = (date(2026, 9, 15), date(2026, 9, 19), "HN-LongBien-SOC")

HUBS = {
    "HCM-ThuDuc-SOC": ("HCM", 0.22), "HCM-TanBinh-Hub": ("HCM", 0.17), "HCM-Q7-Hub": ("HCM", 0.12),
    "HN-LongBien-SOC": ("HN", 0.18), "HN-CauGiay-Hub": ("HN", 0.12),
    "DN-HaiChau-Hub": ("DN", 0.11), "CT-NinhKieu-Hub": ("CT", 0.08),
}

# --------------------------------------------------------------------------------------------
# Comment templates: (dropdown issue_type ground truth, [templates]).  Vietnamese, with accents.
# --------------------------------------------------------------------------------------------
CUSTOMER_NEG = {
    "Late delivery": [
        "Đơn giao trễ quá, hẹn hôm qua mà giờ vẫn chưa nhận được hàng",
        "Giao hàng chậm, chờ gần 1 tuần mới tới",
        "Hàng giao trễ hẹn 3 ngày, không ai báo trước",
        "Đặt hàng lâu quá mà chưa thấy giao",
        "Giao chậm quá, quá hạn dự kiến rồi",
    ],
    "Tracking / status": [
        "Trạng thái đơn không cập nhật, cứ nằm ở kho mãi",
        "Tra cứu vận đơn thấy kẹt ở kho 2 ngày không nhúc nhích",
        "Đơn báo đang xử lý tại kho mãi không đi",
        "Theo dõi đơn không thấy thay đổi gì, không biết khi nào giao",
    ],
    "Failed delivery": [
        "Shipper báo giao không thành công nhưng tôi ở nhà cả ngày",
        "Đơn bị báo giao thất bại dù không ai gọi cho tôi",
    ],
    "Lost / damaged parcel": [
        "Hàng bị móp méo, vỡ đồ bên trong",
        "Mất hàng, đơn báo đã giao mà tôi không nhận được",
    ],
    "Slow response": ["Gọi tổng đài chờ mãi không ai nghe máy", "Chat với CSKH phản hồi chậm quá"],
    "No response": ["Nhắn CSKH 2 ngày rồi chưa được phản hồi", "Gửi yêu cầu hỗ trợ mà không ai trả lời"],
    "Incorrect information": ["Nhân viên tư vấn sai, bảo hôm nay giao mà không giao"],
    "Fee": ["Phí ship cao quá so với chỗ khác"],
    "App issue": ["App SPX bị lỗi không tra cứu được đơn"],
}
CUSTOMER_NEG_W = {"Late delivery": 24, "Tracking / status": 10, "Failed delivery": 10,
                  "Lost / damaged parcel": 8, "Slow response": 8, "No response": 6,
                  "Incorrect information": 5, "Fee": 5, "App issue": 5}

SELLER_NEG = {
    "Late delivery": [
        "Đơn của shop bị giao trễ, khách hủy đơn liên tục",
        "Nhiều đơn của shop giao chậm 3-4 ngày, khách phàn nàn",
        "Đơn shop gửi giao trễ hẹn, bị khách đánh giá 1 sao",
    ],
    "Tracking / status": [
        "Đơn của shop kẹt ở kho không cập nhật trạng thái, khách hỏi mà không biết trả lời",
        "Trạng thái đơn đứng im 2 ngày ở kho",
        "Khách hỏi đơn liên tục vì trạng thái không đổi",
    ],
    "Repeated contact": [
        "Shop phải liên hệ hỗ trợ 3 lần rồi vẫn chưa được xử lý",
        "Gọi đi gọi lại nhiều lần vẫn chưa ai giải quyết",
    ],
    "Pickup delay": ["Tài xế đến lấy hàng trễ, hẹn sáng mà chiều mới tới", "Lấy hàng chậm, đơn tồn ở shop 2 ngày"],
    "Pickup failure": ["Hẹn lấy hàng mà không ai đến lấy"],
    "Failed delivery": [
        "Đơn giao thất bại, khách bảo không ai gọi",
        "Shipper báo khách từ chối nhận nhưng khách nói không hề được gọi",
    ],
    "Failed delivery (after 2 attempts)": [
        "Đơn giao thất bại 2 lần rồi, giờ shop phải làm gì? Có giao lần 3 không?",
        "Giao không thành công 2 lần, không biết đơn sẽ hoàn về shop hay được giao lại",
        "Đơn giao thất bại lần 2, shop không biết bước tiếp theo là gì",
    ],
    "COD": ["Tiền COD chưa được đối soát, chậm 5 ngày rồi", "Chưa nhận được tiền thu hộ tuần trước"],
    "Return": ["Hàng hoàn về shop bị chậm, hoàn cả tuần chưa về"],
    "Compensation": ["Đơn mất hàng mà bồi thường quá lâu, chưa thấy tiền đền bù"],
    "Fee": ["Phí vận chuyển tính sai so với bảng giá"],
}
SELLER_NEG_W = {"Late delivery": 12, "Tracking / status": 8, "Repeated contact": 5, "Pickup delay": 10,
                "Pickup failure": 5, "Failed delivery": 7, "Failed delivery (after 2 attempts)": 5,
                "COD": 12, "Return": 6, "Compensation": 5, "Fee": 5}

RIDER_NEG = {
    "Hub processing delay": [
        "Chờ ở hub quá lâu mới nhận được hàng đi giao",
        "Hub xử lý đơn quá chậm, 10h mới có hàng",
        "Kho chia hàng chậm, tài xế phải đợi 3 tiếng",
        "Hàng ra kho trễ nên giao không kịp",
    ],
    "Wrong routing": ["Hàng bị chia sai tuyến, phải chạy vòng"],
    "App issue": ["App tài xế không đăng nhập được", "App bị văng, không cập nhật được trạng thái giao",
                  "Lỗi đăng nhập app từ sáng"],
    "Delivery attempt": ["Khách không nghe máy, phải giao lại nhiều lần"],
    "Settlement": ["Thu nhập tuần này tính thiếu đơn, chưa đối soát đúng"],
    "Handover issue": ["Shop chưa đóng gói xong, chờ bàn giao hàng lâu"],
}
RIDER_NEG_W = {"Hub processing delay": 12, "Wrong routing": 10, "App issue": 10, "Delivery attempt": 18,
               "Settlement": 12, "Handover issue": 14}

# Hard / ambiguous comments with no obvious keyword — the rule layer should flag them for the LLM.
HARD = {
    "customer": [("Late delivery", "Mình đợi mãi mà chẳng thấy đâu, lần sau chắc không dùng nữa"),
                 ("Tracking / status", "Không biết món hàng của tôi đang ở đâu nữa"),
                 ("Lost / damaged parcel", "Mở ra thì đồ bên trong không còn nguyên vẹn")],
    "seller": [("Settlement", "Tiền bán hàng tuần trước sao vẫn chưa thấy về tài khoản shop"),
               ("Late delivery", "Khách nhắn hỏi suốt mà hàng vẫn chưa tới tay họ")],
    "rider": [("Hub processing delay", "Sáng nào cũng đứng chờ cả buổi mới được đi")],
}
UNCLEAR = ["tệ", "không hài lòng", "chán", "...", "kém", "bình thường", "ok"]
POSITIVE = {
    "customer": ["Giao nhanh, shipper thân thiện", "Hàng nhận đúng hẹn, cảm ơn SPX", "Dịch vụ tốt",
                 "Đóng gói cẩn thận, giao đúng giờ", "ổn", "Rất hài lòng"],
    "seller": ["Lấy hàng đúng giờ, shop hài lòng", "Đối soát nhanh, tốt", "Hỗ trợ nhiệt tình", "ok"],
    "rider": ["Hub chia hàng nhanh hôm nay", "App ổn định", "Tuyến giao hợp lý", "ok"],
}

# Incident extra volume mix (story A)
INC_CUSTOMER = {"Late delivery": 0.6, "Tracking / status": 0.4}
INC_SELLER = {"Tracking / status": 0.4, "Late delivery": 0.35, "Repeated contact": 0.25}
INC_RIDER = {"Hub processing delay": 1.0}

TEEN = [("không", "ko"), ("được", "dc"), ("gì", "j"), ("quá", "wa"), ("rồi", "r"), ("vẫn", "vx"),
        ("giao hàng", "ship hàng"), ("shipper", "shiper")]


def strip_accents(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


def noisify(text, rng):
    r = rng.random()
    if r < 0.18:
        for a, b in TEEN:
            if a in text and rng.random() < 0.7:
                text = text.replace(a, b)
    if rng.random() < 0.10:                                  # stretched letters "lâu quáaaa"
        text = text + rng.choice(["aaa", "!!!", " huhu", " :("])
    if rng.random() < 0.33:
        text = strip_accents(text)
    if rng.random() < 0.15:
        text = text.lower()
    return text


def wchoice(rng, weights):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def pick_hub(rng, exclude=None):
    hubs = {h: w for h, (_, w) in HUBS.items() if h != exclude}
    return wchoice(rng, hubs)


def ts(rng, d):
    return datetime(d.year, d.month, d.day, rng.randint(7, 22), rng.randint(0, 59), rng.randint(0, 59))


def daterange():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def incident_intensity(d):
    """0..1 ramp of story A: starts 14/09, peaks 16-18/09, slightly easing 20/09."""
    if d < INCIDENT_START:
        return 0.0
    return {0: 0.45, 1: 0.8, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.9, 6: 0.8}.get((d - INCIDENT_START).days, 0.8)


class Gen:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.parcels = {}          # tracking_id -> dict(hub, date, delayed)
        self.gt = []               # ground truth for evaluation
        self.cust, self.sell, self.ride, self.tickets = [], [], [], []
        self.n_parcel = 0
        self.sellers = [f"S{n:05d}" for n in range(1, 321)]
        self.riders = {h: [f"R{n:04d}" for n in range(i * 40 + 1, i * 40 + 41)] for i, h in enumerate(HUBS)}

    # ---------------------------------------------------------------- parcels
    def new_parcel(self, hub, d, delayed=False):
        self.n_parcel += 1
        tid = f"SPXVN26{self.n_parcel:07d}"
        self.parcels[tid] = {"hub": hub, "date": d, "delayed": delayed}
        return tid

    # ---------------------------------------------------------------- VOC rows
    def voc(self, stakeholder, d, hub, sub, negative, force_text=None, incident=False):
        rng = self.rng
        region = HUBS[hub][0]
        if force_text is not None:
            text = force_text
        elif negative:
            bank = {"customer": CUSTOMER_NEG, "seller": SELLER_NEG, "rider": RIDER_NEG}[stakeholder]
            text = rng.choice(bank[sub])
            if rng.random() < 0.08:                               # multi-issue comment
                other_sub = rng.choice([s for s in bank if s != sub])
                text = f"{text}, {rng.choice(['còn', 'thêm nữa là', 'với lại'])} {rng.choice(bank[other_sub]).lower()}"
            text = noisify(text, rng)
        else:
            text = noisify(rng.choice(POSITIVE[stakeholder]), rng)

        rating = rng.choice([1, 1, 2, 2, 3]) if negative else rng.choice([4, 5, 5, 5, 3])
        gt_sub = sub if negative else "Positive"
        if gt_sub == "Failed delivery (after 2 attempts)":
            gt_sub = "Failed delivery"
        # survey dropdown: often blank, sometimes wrong (conflict), mostly right
        r = rng.random()
        if not negative:
            dropdown = ""
        elif r < 0.22:
            dropdown = ""
        elif r < 0.27:
            dropdown = rng.choice(["Fee", "App issue", "Slow response", "Return"])
        else:
            dropdown = gt_sub if gt_sub in ALL_SUBS else ""

        row = {"stakeholder_type": stakeholder.capitalize(), "timestamp": ts(rng, d).isoformat(sep=" "),
               "rating": rating, "comment": text, "issue_type": dropdown, "region": region, "hub": hub}
        if stakeholder == "customer":
            fid = f"CV{len(self.cust) + 1:06d}"
            row = {"feedback_id": fid, **row, "stakeholder_id": f"C{rng.randint(1, 999999):06d}"}
            row["tracking_id"] = self.new_parcel(hub, d - timedelta(days=rng.choice([0, 1])), delayed=incident)
            self.cust.append(row)
        elif stakeholder == "seller":
            fid = f"SV{len(self.sell) + 1:06d}"
            sid = rng.choice(self.sellers[:60]) if (incident and rng.random() < 0.6) else rng.choice(self.sellers)
            row = {"feedback_id": fid, **row, "seller_id": sid}
            row["tracking_id"] = self.new_parcel(hub, d - timedelta(days=rng.choice([0, 1])), delayed=incident)
            self.sell.append(row)
        else:
            fid = f"RV{len(self.ride) + 1:06d}"
            row = {"feedback_id": fid, **row, "rider_id": rng.choice(self.riders[hub])}
            self.ride.append(row)
        self.gt.append({"feedback_id": fid, "stakeholder_type": row["stakeholder_type"],
                        "true_sub_issue": gt_sub, "is_incident": int(incident)})
        # tickets: ~35 % of negative feedback also opens a ticket
        if negative and rng.random() < (0.55 if incident else 0.35):
            self.ticket(row, gt_sub, d, hub, incident)
            if incident and stakeholder == "seller" and rng.random() < 0.5:    # repeat contacts
                self.ticket(row, gt_sub, d + timedelta(days=rng.choice([0, 1])), hub, incident)
        return row

    def ticket(self, row, sub, d, hub, incident):
        rng = self.rng
        created = ts(rng, min(d, END))
        sla_h = rng.uniform(4.5, 11) if incident else rng.uniform(0.3, 3.5)
        frt = created + timedelta(hours=sla_h)
        status = rng.choices(["Resolved", "Open", "Pending"], weights=[6, 2, 2] if incident else [8, 1, 1])[0]
        res = "" if status != "Resolved" else (frt + timedelta(hours=rng.uniform(2, 48))).isoformat(sep=" ", timespec="seconds")
        sid = row.get("stakeholder_id") or row.get("seller_id") or row.get("rider_id")
        owner = OWNER_BY_SUB.get(sub, "CS")
        if row["stakeholder_type"] == "Seller" and owner == "CS":
            owner = "SS"
        self.tickets.append({
            "ticket_id": f"TK{len(self.tickets) + 1:06d}", "stakeholder_type": row["stakeholder_type"],
            "stakeholder_id": sid, "created_time": created.isoformat(sep=" "),
            "first_response_time": frt.isoformat(sep=" ", timespec="seconds"), "resolution_time": res,
            "issue_type": sub if sub in ALL_SUBS else "", "description": row["comment"][:160],
            "status": status, "owner_team": owner, "hub": hub, "tracking_id": row.get("tracking_id", ""),
        })

    # ---------------------------------------------------------------- daily loop
    def run(self):
        rng = self.rng
        for d in daterange():
            inten = incident_intensity(d)
            weekday_boost = 1.1 if d.weekday() in (0, 1) else 1.0
            for stakeholder, n_day, neg_share, weights in (
                ("customer", 42, 0.24, CUSTOMER_NEG_W), ("seller", 20, 0.30, SELLER_NEG_W),
                ("rider", 10, 0.34, RIDER_NEG_W),
            ):
                n = max(1, int(rng.gauss(n_day * weekday_boost, n_day * 0.08)))
                for _ in range(n):
                    hub = pick_hub(rng)
                    if rng.random() < 0.035:                         # hard / ambiguous comment
                        sub, txt = rng.choice(HARD[stakeholder])
                        self.voc(stakeholder, d, hub, sub, True, force_text=noisify(txt, rng))
                    elif rng.random() < 0.05:                        # unclear negative
                        self.voc(stakeholder, d, hub, "Unclear", True, force_text=rng.choice(UNCLEAR))
                    elif rng.random() < neg_share:
                        self.voc(stakeholder, d, hub, wchoice(rng, weights), True)
                    else:
                        self.voc(stakeholder, d, hub, None, False)
            # Story A — incident extra volume at the incident hub
            if inten:
                for stakeholder, extra, mix in (("customer", 7, INC_CUSTOMER), ("seller", 4, INC_SELLER),
                                                ("rider", 2, INC_RIDER)):
                    for _ in range(int(round(extra * inten + rng.uniform(-1, 1)))):
                        self.voc(stakeholder, d, INCIDENT_HUB, wchoice(rng, mix), True, incident=True)
            # Story D — rider app login spike in HN
            if APP_SPIKE[0] <= d <= APP_SPIKE[1]:
                for _ in range(rng.randint(3, 4)):
                    self.voc("rider", d, APP_SPIKE[2], "App issue", True)
            # background parcels (not linked to VOC) so ops metrics have volume
            for _ in range(110):
                hub = pick_hub(rng)
                self.new_parcel(hub, d, delayed=False)

    # ---------------------------------------------------------------- ops events
    def ops_events(self):
        rng = self.rng
        rows = []
        for tid, p in self.parcels.items():
            hub, d = p["hub"], p["date"]
            region = HUBS[hub][0]
            degraded = hub == INCIDENT_HUB and d >= OPS_DEGRADE_START
            base = datetime(d.year, d.month, d.day, rng.randint(5, 10), rng.randint(0, 59))
            pickup_lt = max(0.5, rng.gauss(5, 1.5))
            if degraded:
                sev = 1.0 if d > OPS_DEGRADE_START else 0.6
                proc = max(1.0, rng.gauss(4.6 + 4.2 * sev, 1.6))
                if p["delayed"]:
                    proc = max(proc, rng.gauss(10.5, 1.5))
            else:
                proc = max(1.0, rng.gauss(4.6, 1.1))
            inbound = base + timedelta(hours=pickup_lt)
            sorted_t = inbound + timedelta(hours=proc)
            out_t = sorted_t + timedelta(hours=rng.uniform(0.3, 1.5))
            ev = [("pickup", base, 1, round(pickup_lt, 2), "done"),
                  ("inbound_scan", inbound, "", "", "done"),
                  ("sort_complete", sorted_t, "", round(proc, 2), "done"),
                  ("outbound", out_t, "", "", "done")]
            att_t = out_t + timedelta(hours=rng.uniform(2, 8))
            fail_p = 0.07
            for attempt in (1, 2, 3):
                failed = rng.random() < fail_p
                ev.append(("delivery_attempt", att_t, attempt, "", "failed" if failed else "delivered"))
                if not failed:
                    break
                att_t += timedelta(hours=rng.uniform(20, 28))
                fail_p = 0.35
            for et, t, att, pt, st in ev:
                rows.append({"event_id": "", "timestamp": t.isoformat(sep=" ", timespec="seconds"),
                             "tracking_id": tid, "event_type": et, "hub": hub, "region": region,
                             "delivery_attempt": att, "processing_time": pt, "status": st})
        rows.sort(key=lambda r: (r["timestamp"], r["tracking_id"]))
        for i, r in enumerate(rows, 1):
            r["event_id"] = f"EV{i:07d}"
        return rows


ALL_SUBS = {"Late delivery", "Failed delivery", "Delivery attempt", "Return", "Tracking / status",
            "Pickup delay", "Pickup failure", "Handover issue", "Hub processing delay",
            "Lost / damaged parcel", "Wrong routing", "COD", "Settlement", "Fee", "Compensation",
            "Slow response", "No response", "Incorrect information", "Repeated contact",
            "App issue", "Account issue", "Feature issue"}
OWNER_BY_SUB = {"Late delivery": "Operations", "Tracking / status": "Operations", "Hub processing delay": "Operations",
                "Failed delivery": "Operations", "Delivery attempt": "Operations", "Wrong routing": "Operations",
                "Lost / damaged parcel": "Operations", "Pickup delay": "Operations", "Pickup failure": "Operations",
                "Handover issue": "Operations", "Return": "Operations", "COD": "Finance", "Settlement": "Finance",
                "Fee": "Finance", "Compensation": "CS", "App issue": "Product", "Account issue": "Product",
                "Feature issue": "Product"}

HELP_CENTER = [
    ("HC-001", "Vì sao đơn hàng của tôi bị giao trễ?", "Late delivery",
     "Đơn có thể giao trễ do thời tiết, cao điểm hoặc địa chỉ khó tìm. Bạn có thể theo dõi trạng thái đơn trên app. "
     "Nếu đơn quá thời gian dự kiến 2 ngày, vui lòng liên hệ CSKH để được hỗ trợ.", "CS", "2026-06-02"),
    ("HC-002", "Cách tra cứu trạng thái vận đơn", "Tracking / status",
     "Nhập mã vận đơn trên app hoặc website để xem hành trình. Trạng thái được cập nhật tại mỗi lần quét ở kho.",
     "CS", "2026-05-10"),
    ("HC-003", "Shop: đơn không cập nhật trạng thái thì làm sao?", "Tracking / status",
     "Shop kiểm tra hành trình trên Seller Center. Nếu trạng thái đứng yên quá 48 giờ, shop tạo yêu cầu hỗ trợ kèm mã vận đơn.",
     "SS", "2026-04-18"),
    ("HC-004", "Giao hàng không thành công", "Failed delivery",
     "Đơn có thể giao không thành công khi người nhận vắng nhà, không nghe máy hoặc từ chối nhận. "
     "Tài xế sẽ ghi nhận lý do trên hệ thống. Shop có thể xem lý do trong chi tiết đơn.", "SS", "2026-03-21"),
    ("HC-005", "Thời gian đối soát tiền thu hộ (COD)", "COD",
     "Tiền COD được đối soát theo chu kỳ hàng tuần và chuyển về tài khoản ngân hàng của shop.", "Finance", "2025-09-15"),
    ("HC-006", "Hẹn lấy hàng và thời gian lấy hàng", "Pickup delay",
     "Tài xế sẽ đến lấy hàng trong khung giờ đã hẹn. Nếu quá khung giờ, shop có thể yêu cầu lấy lại trên Seller Center.",
     "Operations", "2026-07-01"),
    ("HC-007", "Chính sách bồi thường hàng mất / hư hỏng", "Compensation",
     "SPX bồi thường theo giá trị khai báo. Thời gian xử lý bồi thường từ 7 đến 14 ngày làm việc.", "CS", "2026-02-11"),
    ("HC-008", "Tài xế: quy trình nhận hàng tại hub", "Hub processing delay",
     "Tài xế đến hub theo ca đã đăng ký, nhận hàng sau khi hub hoàn tất chia chọn. Liên hệ trưởng ca nếu thời gian chờ vượt quá 60 phút.",
     "Operations", "2026-01-20"),
    ("HC-009", "Tài xế: không đăng nhập được app", "App issue",
     "Kiểm tra kết nối mạng, cập nhật app lên bản mới nhất và đăng nhập lại. Nếu vẫn lỗi, gửi yêu cầu qua kênh hỗ trợ tài xế.",
     "Product", "2026-08-01"),
    ("HC-010", "Phí vận chuyển được tính thế nào?", "Fee",
     "Phí vận chuyển dựa trên khối lượng, kích thước và khu vực giao. Xem bảng giá chi tiết trên website.", "Finance", "2026-05-30"),
    ("HC-011", "Hàng hoàn về shop mất bao lâu?", "Return",
     "Đơn hoàn sẽ được trả về shop trong 3-7 ngày tùy khu vực.", "Operations", "2026-04-02"),
    ("HC-012", "Liên hệ bộ phận hỗ trợ", "Slow response",
     "Bạn có thể liên hệ qua hotline hoặc chat. Thời gian phản hồi mục tiêu là 4 giờ làm việc.", "CS", "2026-06-15"),
]


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def generate(out_dir, seed=42):
    os.makedirs(out_dir, exist_ok=True)
    g = Gen(seed)
    g.run()
    ops = g.ops_events()
    write_csv(os.path.join(out_dir, "customer_voc.csv"), g.cust,
              ["feedback_id", "stakeholder_type", "stakeholder_id", "timestamp", "rating", "comment", "issue_type",
               "region", "hub", "tracking_id"])
    write_csv(os.path.join(out_dir, "seller_voc.csv"), g.sell,
              ["feedback_id", "stakeholder_type", "seller_id", "timestamp", "rating", "comment", "issue_type",
               "region", "hub", "tracking_id"])
    write_csv(os.path.join(out_dir, "rider_voc.csv"), g.ride,
              ["feedback_id", "stakeholder_type", "rider_id", "timestamp", "rating", "comment", "issue_type",
               "region", "hub"])
    write_csv(os.path.join(out_dir, "support_tickets.csv"), sorted(g.tickets, key=lambda t: t["created_time"]),
              ["ticket_id", "stakeholder_type", "stakeholder_id", "created_time", "first_response_time",
               "resolution_time", "issue_type", "description", "status", "owner_team", "hub", "tracking_id"])
    write_csv(os.path.join(out_dir, "operational_events.csv"), ops,
              ["event_id", "timestamp", "tracking_id", "event_type", "hub", "region", "delivery_attempt",
               "processing_time", "status"])
    write_csv(os.path.join(out_dir, "help_center.csv"),
              [dict(zip(["article_id", "title", "issue_type", "content", "owner_team", "last_updated"], a))
               for a in HELP_CENTER],
              ["article_id", "title", "issue_type", "content", "owner_team", "last_updated"])
    write_csv(os.path.join(out_dir, "_ground_truth.csv"), g.gt,
              ["feedback_id", "stakeholder_type", "true_sub_issue", "is_incident"])
    return {"customer_voc": len(g.cust), "seller_voc": len(g.sell), "rider_voc": len(g.ride),
            "support_tickets": len(g.tickets), "operational_events": len(ops), "help_center": len(HELP_CENTER)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate synthetic SPX VOC data")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "synthetic"))
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    for k, v in generate(a.out, a.seed).items():
        print(f"{k:>20}: {v:,}")
