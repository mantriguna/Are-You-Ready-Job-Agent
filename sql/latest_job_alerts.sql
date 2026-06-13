create table if not exists public.latest_job_alerts (
  whatsapp_number text not null references public.user_profiles(whatsapp_number) on delete cascade,
  job_number integer not null,
  job_id text not null,
  title text not null,
  company text not null,
  location text,
  job_url text not null,
  description text,
  match_percentage integer,
  evaluation jsonb not null default '{}'::jsonb,
  resume_file text,
  created_at timestamptz not null default now(),
  primary key (whatsapp_number, job_number)
);

alter table public.latest_job_alerts enable row level security;
