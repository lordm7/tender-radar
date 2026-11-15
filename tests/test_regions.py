from tender_radar.regions import infer_region


def test_city_maps_to_region():
    assert infer_region("أمانة محافظة جدة") == "مكة المكرمة"
    assert infer_region("بلدية الخبر") == "المنطقة الشرقية"
    assert infer_region("مستشفى أبها العام") == "عسير"


def test_region_name_directly():
    assert infer_region("فرع الوزارة بمنطقة الرياض") == "الرياض"
    assert infer_region("إمارة منطقة القصيم") == "القصيم"


def test_no_region_returns_none():
    assert infer_region("وزارة الخدمات الرقمية") is None
    assert infer_region("") is None


def test_first_mention_wins():
    assert infer_region("فرع جدة التابع لإدارة الرياض") == "مكة المكرمة"
