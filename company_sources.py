from dataclasses import dataclass, field
from urllib.parse import urlparse


DEFAULT_PREFERRED_LOCATIONS = [
    "Hyderabad",
    "Bengaluru",
    "Bangalore",
    "Chennai",
    "Pune",
    "Gurugram",
    "Gurgaon",
    "Noida",
    "Mumbai",
    "Remote",
]


@dataclass(frozen=True)
class CompanySource:
    company_name: str
    careers_url: str
    enabled: bool = True
    priority: int = 100
    source_type: str = "generic_html"
    source_key: str | None = None
    allowed_countries: list[str] = field(default_factory=lambda: ["India"])
    preferred_locations: list[str] = field(default_factory=lambda: DEFAULT_PREFERRED_LOCATIONS)
    official_domains: list[str] = field(default_factory=list)

    @property
    def domain(self) -> str:
        return urlparse(self.careers_url).netloc.lower()

    def is_official_domain(self) -> bool:
        domain = self.domain.removeprefix("www.")
        allowed = self.official_domains or [domain]
        return any(
            domain == item.lower().removeprefix("www.")
            or domain.endswith(f".{item.lower().removeprefix('www.')}")
            for item in allowed
        )


DEFAULT_COMPANY_SOURCES: list[CompanySource] = [
    CompanySource("Amazon", "https://www.amazon.jobs/en/search?base_query=software&loc_query=India", priority=1, source_type="amazon_json", official_domains=["amazon.jobs"]),
    CompanySource("Microsoft", "https://jobs.careers.microsoft.com/global/en/search?lc=India", priority=2, official_domains=["jobs.careers.microsoft.com"]),
    CompanySource("Google", "https://www.google.com/about/careers/applications/jobs/results/?location=India", priority=3, official_domains=["google.com"]),
    CompanySource("Atlassian", "https://www.atlassian.com/company/careers/all-jobs", priority=4, official_domains=["atlassian.com"]),
    CompanySource("Uber", "https://www.uber.com/in/en/careers/list/", priority=5, official_domains=["uber.com"]),
    CompanySource("Salesforce", "https://careers.salesforce.com/en/jobs/", priority=6, official_domains=["careers.salesforce.com"]),
    CompanySource("ServiceNow", "https://careers.servicenow.com/jobs/", priority=7, official_domains=["careers.servicenow.com"]),
    CompanySource("Walmart Global Tech", "https://tech.walmart.com/content/walmart-global-tech/en_us/careers.html", priority=8, official_domains=["tech.walmart.com", "walmart.com"]),
    CompanySource("Adobe", "https://careers.adobe.com/us/en/search-results?keywords=software&location=India", priority=9, official_domains=["careers.adobe.com"]),
    CompanySource("Intuit", "https://jobs.intuit.com/search-jobs/India/", priority=10, official_domains=["jobs.intuit.com"]),
    CompanySource("NVIDIA", "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", priority=20, source_type="workday", official_domains=["nvidia.wd5.myworkdayjobs.com"]),
    CompanySource("Qualcomm", "https://careers.qualcomm.com/careers", priority=21, official_domains=["careers.qualcomm.com"]),
    CompanySource("Cisco", "https://jobs.cisco.com/", priority=22, official_domains=["jobs.cisco.com"]),
    CompanySource("Oracle", "https://www.oracle.com/in/careers/", priority=23, official_domains=["oracle.com"]),
    CompanySource("PayPal", "https://paypal.eightfold.ai/careers", priority=24, official_domains=["paypal.eightfold.ai"]),
    CompanySource(
        "Visa",
        "https://corporate.visa.com/en/careers.html",
        priority=25,
        source_type="workday",
        source_key="https://visa.wd5.myworkdayjobs.com/Visa",
        official_domains=["corporate.visa.com", "visa.wd5.myworkdayjobs.com"],
    ),
    CompanySource("JPMorgan Chase", "https://www.jpmorganchase.com/careers", priority=26, official_domains=["jpmorganchase.com"]),
    CompanySource("Goldman Sachs", "https://higher.gs.com/", priority=27, official_domains=["higher.gs.com"]),
    CompanySource("Morgan Stanley", "https://www.morganstanley.com/people-opportunities/students-graduates", priority=28, official_domains=["morganstanley.com"]),
    CompanySource("American Express", "https://aexp.eightfold.ai/careers", priority=29, official_domains=["aexp.eightfold.ai"]),
    CompanySource(
        "Wells Fargo",
        "https://www.wellsfargojobs.com/en/jobs/",
        priority=30,
        source_type="workday",
        source_key="https://wf.wd1.myworkdayjobs.com/WellsFargoJobs",
        official_domains=["wellsfargojobs.com", "wf.wd1.myworkdayjobs.com"],
    ),
    CompanySource("Mastercard", "https://careers.mastercard.com/us/en/search-results", priority=31, official_domains=["careers.mastercard.com"]),
    CompanySource("SAP Labs", "https://jobs.sap.com/", priority=32, official_domains=["jobs.sap.com"]),
    CompanySource("Dell Technologies", "https://jobs.dell.com/", priority=33, official_domains=["jobs.dell.com"]),
    CompanySource("Broadcom", "https://broadcom.wd1.myworkdayjobs.com/External_Career", priority=34, source_type="workday", official_domains=["broadcom.wd1.myworkdayjobs.com"]),
    CompanySource("Apple India", "https://jobs.apple.com/en-in/search?location=india-INDC", priority=35, official_domains=["jobs.apple.com"]),
    CompanySource("Flipkart", "https://www.flipkartcareers.com/", priority=40, official_domains=["flipkartcareers.com"]),
    CompanySource("PhonePe", "https://www.phonepe.com/careers/", priority=41, source_type="greenhouse", source_key="phonepe", official_domains=["phonepe.com"]),
    CompanySource("Razorpay", "https://razorpay.com/careers/", priority=42, source_type="greenhouse", source_key="razorpaysoftwareprivatelimited", official_domains=["razorpay.com"]),
    CompanySource("Meesho", "https://www.meesho.io/jobs", priority=43, source_type="lever", source_key="meesho", official_domains=["meesho.io"]),
    CompanySource("Swiggy", "https://careers.swiggy.com/", priority=44, official_domains=["careers.swiggy.com"]),
    CompanySource("Zomato", "https://www.zomato.com/careers", priority=45, official_domains=["zomato.com"]),
    CompanySource("CRED", "https://careers.cred.club/", priority=46, source_type="lever", source_key="cred", official_domains=["careers.cred.club"]),
    CompanySource("Groww", "https://groww.in/careers", priority=47, source_type="greenhouse", source_key="groww", official_domains=["groww.in"]),
    CompanySource("BrowserStack", "https://www.browserstack.com/careers", priority=48, source_type="workday", source_key="https://browserstack.wd3.myworkdayjobs.com/External", official_domains=["browserstack.com"]),
    CompanySource("Postman", "https://www.postman.com/company/careers/", priority=49, source_type="greenhouse", source_key="postman", official_domains=["postman.com"]),
    CompanySource("Freshworks", "https://www.freshworks.com/company/careers/", priority=50, official_domains=["freshworks.com"]),
    CompanySource("Zoho", "https://www.zoho.com/careers/", priority=51, official_domains=["zoho.com"]),
    CompanySource("Dream Sports", "https://www.dreamsports.group/careers/", priority=52, source_type="lever", source_key="dreamsports", official_domains=["dreamsports.group"]),
    CompanySource("Juspay", "https://juspay.io/careers", priority=53, official_domains=["juspay.io"]),
    CompanySource("Zepto", "https://www.zepto.com/s/careers", priority=54, official_domains=["zepto.com"]),
]


def get_enabled_company_sources() -> list[CompanySource]:
    return [source for source in DEFAULT_COMPANY_SOURCES if source.enabled and source.is_official_domain()]
