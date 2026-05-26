create extension if not exists pgcrypto;

create table if not exists public.user_profiles (
  whatsapp_number text primary key,
  user_name text,
  target_title text,
  experience_summary text,
  resume_text text,
  alert_time time without time zone default '09:00' not null,
  onboarding_state text default 'new' not null,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null
);

create table if not exists public.sent_jobs (
  whatsapp_number text not null references public.user_profiles(whatsapp_number) on delete cascade,
  job_id text not null,
  job_title text,
  company_name text,
  job_url text,
  match_percentage integer,
  sent_at timestamp with time zone default now() not null,
  primary key (whatsapp_number, job_id)
);

alter table public.user_profiles enable row level security;
alter table public.sent_jobs enable row level security;

create index if not exists idx_user_profiles_alert_time
  on public.user_profiles (alert_time);

create index if not exists idx_sent_jobs_whatsapp_sent_at
  on public.sent_jobs (whatsapp_number, sent_at desc);

create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists set_user_profiles_updated_at on public.user_profiles;

create trigger set_user_profiles_updated_at
before update on public.user_profiles
for each row
execute function public.set_updated_at();
