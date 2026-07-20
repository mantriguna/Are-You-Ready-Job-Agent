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
    CompanySource("Stripe", "https://stripe.com/jobs", priority=55, source_type="greenhouse", source_key="stripe", official_domains=["stripe.com"]),
    CompanySource("Rubrik", "https://www.rubrik.com/company/careers", priority=56, source_type="greenhouse", source_key="rubrik", official_domains=["rubrik.com"]),
    CompanySource("Databricks", "https://www.databricks.com/company/careers/open-positions", priority=57, source_type="greenhouse", source_key="databricks", official_domains=["databricks.com"]),
    CompanySource("Tekion", "https://tekion.com/careers", priority=58, source_type="greenhouse", source_key="tekion", official_domains=["tekion.com"]),
    CompanySource("Coinbase", "https://www.coinbase.com/careers", priority=59, source_type="greenhouse", source_key="coinbase", official_domains=["coinbase.com"]),
    CompanySource("Okta", "https://www.okta.com/company/careers/", priority=60, source_type="greenhouse", source_key="okta", official_domains=["okta.com"]),
    CompanySource("Zscaler", "https://www.zscaler.com/careers", priority=61, source_type="greenhouse", source_key="zscaler", official_domains=["zscaler.com"]),
    CompanySource("Netskope", "https://www.netskope.com/company/careers/", priority=62, source_type="greenhouse", source_key="netskope", official_domains=["netskope.com"]),
    CompanySource("MongoDB", "https://www.mongodb.com/careers", priority=63, source_type="greenhouse", source_key="mongodb", official_domains=["mongodb.com"]),
    CompanySource("Elastic", "https://www.elastic.co/careers", priority=64, source_type="greenhouse", source_key="elastic", official_domains=["elastic.co"]),
    CompanySource("Twilio", "https://www.twilio.com/en-us/company/jobs", priority=65, source_type="greenhouse", source_key="twilio", official_domains=["twilio.com"]),
    CompanySource("GitLab", "https://about.gitlab.com/jobs/", priority=66, source_type="greenhouse", source_key="gitlab", official_domains=["about.gitlab.com", "gitlab.com"]),
    CompanySource("Figma", "https://www.figma.com/careers/", priority=67, source_type="greenhouse", source_key="figma", official_domains=["figma.com"]),
    CompanySource("Instabase", "https://www.instabase.com/careers/", priority=68, source_type="greenhouse", source_key="instabase", official_domains=["instabase.com"]),
    CompanySource("Datadog", "https://www.datadoghq.com/careers/", priority=69, source_type="greenhouse", source_key="datadog", official_domains=["datadoghq.com"]),
    CompanySource("Cloudflare", "https://www.cloudflare.com/careers/jobs/", priority=70, source_type="greenhouse", source_key="cloudflare", official_domains=["cloudflare.com"]),
    CompanySource("Sumo Logic", "https://www.sumologic.com/company/careers/", priority=71, source_type="greenhouse", source_key="sumologic", official_domains=["sumologic.com"]),
    CompanySource("New Relic", "https://newrelic.com/careers", priority=72, source_type="greenhouse", source_key="newrelic", official_domains=["newrelic.com"]),
    CompanySource("Pure Storage", "https://www.purestorage.com/company/careers.html", priority=73, source_type="greenhouse", source_key="purestorage", official_domains=["purestorage.com"]),
    CompanySource("InMobi", "https://www.inmobi.com/company/careers/", priority=74, source_type="greenhouse", source_key="inmobi", official_domains=["inmobi.com"]),
    CompanySource("Snowflake", "https://careers.snowflake.com/us/en", priority=75, source_type="ashby", source_key="snowflake", official_domains=["careers.snowflake.com"]),
    CompanySource("Confluent", "https://www.confluent.io/careers/", priority=76, source_type="ashby", source_key="confluent", official_domains=["confluent.io"]),
    CompanySource("Notion", "https://www.notion.com/careers", priority=77, source_type="ashby", source_key="notion", official_domains=["notion.com"]),
    CompanySource("Zapier", "https://zapier.com/jobs", priority=78, source_type="ashby", source_key="zapier", official_domains=["zapier.com"]),
    CompanySource("HackerRank", "https://www.hackerrank.com/careers/", priority=79, source_type="greenhouse", source_key="hackerrank", official_domains=["hackerrank.com"]),
    CompanySource("ZoomInfo", "https://www.zoominfo.com/careers", priority=80, source_type="greenhouse", source_key="zoominfo", official_domains=["zoominfo.com"]),
    CompanySource("Bloomreach", "https://www.bloomreach.com/en/about/careers", priority=81, source_type="greenhouse", source_key="bloomreach", official_domains=["bloomreach.com"]),
    CompanySource("LogicMonitor", "https://www.logicmonitor.com/careers", priority=82, source_type="greenhouse", source_key="logicmonitor", official_domains=["logicmonitor.com"]),
    CompanySource("ClickHouse", "https://clickhouse.com/company/careers", priority=83, source_type="greenhouse", source_key="clickhouse", official_domains=["clickhouse.com"]),
    CompanySource("Adyen", "https://careers.adyen.com", priority=84, source_type="greenhouse", source_key="adyen", official_domains=["careers.adyen.com", "adyen.com"]),
    CompanySource("Observe.AI", "https://www.observe.ai/careers", priority=85, source_type="greenhouse", source_key="observeai", official_domains=["observe.ai"]),
    CompanySource("Yugabyte", "https://www.yugabyte.com/careers", priority=86, source_type="greenhouse", source_key="yugabyte", official_domains=["yugabyte.com"]),
    CompanySource("Truecaller", "https://www.truecaller.com/careers", priority=87, source_type="greenhouse", source_key="truecaller", official_domains=["truecaller.com"]),
    CompanySource("Agoda", "https://careersatagoda.com", priority=88, source_type="greenhouse", source_key="agoda", official_domains=["careersatagoda.com", "agoda.com"]),
    CompanySource("Druva", "https://www.druva.com/about/careers/", priority=89, source_type="greenhouse", source_key="druva", official_domains=["druva.com"]),
    CompanySource("FourKites", "https://www.fourkites.com/careers/", priority=90, source_type="greenhouse", source_key="fourkites", official_domains=["fourkites.com"]),
    CompanySource("Zeta", "https://www.zeta.tech/careers", priority=91, source_type="lever", source_key="zeta", official_domains=["zeta.tech"]),
    CompanySource("Paytm", "https://paytm.com/careers", priority=92, source_type="lever", source_key="paytm", official_domains=["paytm.com"]),
    CompanySource("Sophos", "https://www.sophos.com/en-us/careers", priority=93, source_type="lever", source_key="sophos", official_domains=["sophos.com"]),
    CompanySource("Atlan", "https://atlan.com/careers", priority=94, source_type="ashby", source_key="atlan", official_domains=["atlan.com"]),
]


def get_enabled_company_sources() -> list[CompanySource]:
    return [source for source in DEFAULT_COMPANY_SOURCES if source.enabled and source.is_official_domain()]
