# تغییرات نسخهٔ ۳.۱

این نسخه، **اصلاحات ۲.۱** را به شاخهٔ **۳.۰** (پروفایل‌های کسب‌وکار ایرانی و اتصال
WooCommerce) می‌آورد؛ تا پیش از این، دو خط توسعه جدا بودند و نسخهٔ ۲.۱ هیچ‌کدام از
قابلیت‌های ۳.۰ را نداشت. Schema در نسخهٔ **۵** باقی می‌ماند و مهاجرت خودکار است.

## قابلیت‌های نسخهٔ ۳.۰ که اکنون در دسترس است

- **۲۰ پروفایل کسب‌وکار** (`business_profiles.py`): انتخاب در راه‌اندازی اولیه و تغییر
  از تنظیمات؛ عنوان فعالیت، صفحه‌های پیشنهادی، KPIها و واحد/انبار پیش‌فرض.
- **ویژگی‌های کالا بر اساس پروفایل** (`items.metadata_json`): بارکد، انقضا، برند، تنوع،
  سریال/IMEI، OEM، شابک و …؛ ستون «ویژگی‌های پروفایل» در فهرست کالاها.
- **اتصال WooCommerce** (`wc/v3` روی HTTPS + Basic Auth): همگام‌سازی کالا/قیمت/SKU،
  موجودی از دفتر انبار، مشتری (با ایمیل) و سفارش‌ها به‌صورت فاکتور و سند دوبل؛
  صف خروجی با retry (`sync_outbox`)، idempotency، Webhook با HMAC و polling.
- **فیلد ایمیل طرف حساب** برای نگاشت مشتری ووکامرس ↔ طرف حساب محلی.

## اصلاحات حسابداری نسخهٔ ۲.۱ (اکنون روی این شاخه)

| # | مشکل | تست |
|---|------|-----|
| ۱ | سود ناخالص ردیف برگشت از فروش با دفتر کل نمی‌خواند | `test_sale_return_row_profit_matches_ledger` |
| ۲ | ارزش‌گذاری برگشت وقتی موجودی صفر است (ارزش ۰ ثبت می‌شد) | `test_sale_return_valued_at_original_cost_when_stock_is_zero` |
| ۳ | برگشت بیش از مقدار فروش/خرید | `test_return_cannot_exceed_sold_quantity` |
| ۴ | ابطال فاکتور خریدِ فروش‌رفته و منفی‌شدن انبار | `test_cancel_purchase_cannot_make_negative_stock` |
| ۵ | غیرفعال‌سازی کالای دارای موجودی | `test_deactivating_item_with_stock_is_rejected` |
| ۶ | ماندهٔ اولیهٔ شخص که بی‌صدا نادیده گرفته می‌شد | `test_party_opening_is_recorded_and_not_silently_changed` |
| ۷ | ماندهٔ اولیه در دورهٔ قفل‌شده (سند ثبت نمی‌شد) | `test_opening_balance_is_atomic_in_locked_period` |
| ۸ | دریافت/پرداخت بدون ارجاع بیش از مانده | `test_overpayment_without_invoice_is_rejected` |
| ۹ | ماندهٔ شخص غیرفعال در گزارش‌ها | `test_inactive_party_balance_still_reported` |
| ۱۰ | خطای خام کد تکراری کالا | `test_duplicate_item_code_raises_readable_error` |

## اصلاحات نمایش و واحد پول

- `repo.money_unit()` و `repo.unit_label()` در همهٔ برگه‌ها، سرفصل ستون‌ها، برچسب فرم‌ها،
  فاکتور چاپی و **برچسب ضریب قیمت ووکامرس** اعمال می‌شود؛ ذخیره‌سازی همچنان به ریال صحیح.
- `MoneyEdit` بدون مسیر `float` (ورودی‌های بزرگ دقیق می‌مانند) و یکسان با `utils.parse_money`.
- تنظیم مجوز `period.lock` برای نقش حسابدار و تست پوشش مجوزها.

## اعتبارسنجی این نسخه

```text
python -m pytest -q            →  ۳۴ موفق (۱ skip در محیط بدون Qt)
python tests/test_logic.py     →  ۳۶ موفق
python tests/test_features.py  →  ۴۴ موفق
ruff check .                   →  بدون خطا
build_exe.py --dry-run          →  schema_embedded.py هم‌خوان (schema 5)
```

## آنچه عمداً تغییر نکرد

- شِمای پایگاه داده ارتقای اجباری نگرفت (همان نسخهٔ ۵)؛ دادهٔ موجود بدون مهاجرت باز می‌شود.
- گردش‌کار سفارش لغوشده/refund در ووکامرس به‌صورت خودکار معکوس **نمی‌شود** و برای
  بررسی دستی علامت‌گذاری می‌شود (همان تصمیم نسخهٔ ۳.۰، جزئیات در
  `docs/BUSINESS-PROFILES-WOOCOMMERCE.md`).
