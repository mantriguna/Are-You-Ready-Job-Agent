create table if not exists public.incoming_whatsapp_messages (
  message_id text primary key,
  whatsapp_number text not null,
  received_at timestamptz not null default now()
);

alter table public.incoming_whatsapp_messages enable row level security;

create index if not exists idx_incoming_whatsapp_messages_received_at
  on public.incoming_whatsapp_messages (received_at desc);
