/* global Response, URL, location, setTimeout */
const now = new Date().toISOString();

const me = {
  id: 1,
  full_name: "小可爱",
  username: "kmua_fan",
  lang: "zh-CN",
  coins: 3280,
  affection: 886,
  affection_percentile: 0.92,
  waifu_mention: true,
  is_married: true,
  married_waifu_id: 2,
  married_waifu_name: "小喵",
  quote_count: 3,
  gift_count: 2,
  chat_count: 3,
  roles: ["global_admin"],
};

const chats = [
  { id: -1001001, title: "喵喵同好会", username: "kmua_club", can_manage: true },
  { id: -1001002, title: "周末茶话会", username: null, can_manage: true },
  { id: -1001003, title: "二次元研究所", username: "acg_lab", can_manage: false },
];

const config = {
  waifu_enabled: true,
  delete_events_enabled: false,
  unpin_channel_pin_enabled: true,
  quote_probability: 0.125,
  quote_pin_message: true,
  title_permissions: { can_change_info: true, can_delete_messages: true },
  greeting: "欢迎 ${user} 来到 ${chat}，今天也要开心喵～",
  ai_reply: true,
  ai_reply_other_bots_enabled: false,
  ai_comment: true,
  setu_enabled: true,
  convert_b23_enabled: true,
  parse_links_enabled: true,
  parse_artwork_enabled: true,
  parse_sites_enabled: { bilibili: true, pixiv: true, twitter: false },
  pick_bottle_enabled: true,
  group_memory_enabled: true,
  sticker_memory_enabled: true,
  parse_wechat_enabled: true,
  rss_agent_summary: true,
  rss_agent_broadcast: false,
  verify_enabled: true,
  verify_strategy: "first_message",
  verify_method: "math_easy",
  verify_max_attempts: 3,
  verify_timeout_seconds: 120,
  verify_fail_action: "kick",
  verify_questions: [],
  lang: "zh-CN",
};

const quotes = [
  {
    link: "https://t.me/kmua_club/101",
    chat_id: -1001001,
    chat_title: "喵喵同好会",
    user_id: 2,
    user_name: "小喵",
    message_id: 101,
    text: "今天也要元气满满喵！",
    has_image: false,
    created_at: now,
  },
  {
    link: "https://t.me/kmua_club/102",
    chat_id: -1001001,
    chat_title: "喵喵同好会",
    user_id: 3,
    user_name: "桃子",
    message_id: 102,
    text: "可爱就是正义！",
    has_image: true,
    created_at: now,
  },
  {
    link: "https://t.me/kmua_club/103",
    chat_id: -1001001,
    chat_title: "喵喵同好会",
    user_id: 1,
    user_name: "小可爱",
    message_id: 103,
    text: "把每一天都变成可爱的回忆。",
    has_image: false,
    created_at: now,
  },
];

const catalog = [
  {
    gift_id: "sakura",
    display_name: "樱花发卡",
    description: "别在耳边的春日心意",
    comment: "好感度小小上升",
    price: 88,
  },
  {
    gift_id: "pudding",
    display_name: "猫猫布丁",
    description: "duang duang 的甜蜜点心",
    comment: "获得今日好心情",
    price: 128,
  },
  {
    gift_id: "star",
    display_name: "许愿星星",
    description: "把愿望藏进星光里",
    comment: "随机触发惊喜效果",
    price: 520,
  },
];

const gifts = [
  {
    id: 1,
    gift_id: "sakura",
    display_name: "樱花发卡",
    rarity: 2,
    rarity_name: "珍稀",
    sent_to_bot: false,
    created_at: now,
  },
  {
    id: 2,
    gift_id: "pudding",
    display_name: "猫猫布丁",
    rarity: 1,
    rarity_name: "凡芽",
    sent_to_bot: false,
    created_at: now,
  },
];

const feeds = [
  {
    id: 1,
    feed_id: 1,
    url: "https://example.com/anime.xml",
    title: "新番更新小站",
    paused: false,
    interval_minutes: 30,
    last_error: null,
    last_fetched_at: now,
    created_at: now,
  },
  {
    id: 2,
    feed_id: 2,
    url: "https://example.com/daily.xml",
    title: "每日可爱速递",
    paused: true,
    interval_minutes: null,
    last_error: null,
    last_fetched_at: now,
    created_at: now,
  },
];

const waifu = {
  is_married: true,
  married_waifu_id: 2,
  married_waifu_name: "小喵",
  entries: [
    { chat_id: -1001001, chat_title: "喵喵同好会", waifu_id: 2, waifu_name: "小喵" },
    { chat_id: -1001002, chat_title: "周末茶话会", waifu_id: 4, waifu_name: "奈奈" },
  ],
};

const stats = {
  users: 12680,
  chats: 328,
  quotes: 45678,
  associations: 8930,
  bottles: 1204,
  affection: { total_users: 12680, bucket_count: 28, min_bucket: 0, max_bucket: 999 },
  dashboard: {
    user_structure: { real_users: 12036, married_users: 886 },
    recent: { quotes: 328, bottles: 66 },
    bottle_interactions: { picks: 520 },
  },
  runtime: {
    uptime_seconds: 86420,
    max_rss_bytes: 268435456,
    threads: 8,
    tasks: 32,
    loop_lag_ms: 1.8,
    loop_lag_p95_ms: 5.2,
    loop_lag_max_ms: 12.5,
    loop_stalls: 0,
    telegram_update_types: { UpdateNewMessage: 886, UpdateBotCallbackQuery: 66 },
    group_activity: [{ chat_id: -1001001, events: 328 }],
    feature_calls: { quote: 328, waifu: 166 },
    telegram_updates: { 300: 952 },
    api_requests: { 300: 328 },
    api_latency_ms: { p95: 28 },
  },
};

const adminUsers = chats.map((chat, index) => ({
  id: index + 1,
  full_name: ["小可爱", "小喵", "桃子"][index],
  username: ["kmua_fan", "miao", "momo"][index],
  lang: "zh-CN",
  coins: 3280 - index * 100,
  affection: 886 - index * 50,
  waifu_mention: true,
  is_bot: false,
  is_real_user: true,
  is_bot_global_admin: index === 0,
  is_blocked: false,
  is_owner: false,
  is_married: index === 0,
  married_waifu_id: index === 0 ? 2 : null,
  created_at: now,
  chats: [chat],
  quote_count: 3,
  gift_count: 2,
  agent_quota: null,
}));

function page(items, url) {
  const size = Number(url.searchParams.get("size") ?? 20);
  const pageNumber = Number(url.searchParams.get("page") ?? 1);
  return {
    items: items.slice((pageNumber - 1) * size, pageNumber * size),
    total: items.length,
    page: pageNumber,
    size,
  };
}

function json(data, status = 200) {
  return new Response(data === undefined ? null : JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function chatDetail(id) {
  const chat = chats.find((item) => item.id === id) ?? chats[0];
  return {
    ...chat,
    member_count: 886,
    quote_count: 328,
    config,
    created_at: now,
    is_blocked: false,
  };
}

function respond(method, path, url, body) {
  if (method === "GET" && path === "/api/system/info")
    return {
      bot_username: "kmua_bot",
      panel_enabled: true,
      available_locales: ["zh-CN", "zh-Hant", "en"],
    };
  if (method === "GET" && path === "/api/me") return me;
  if (method === "PATCH" && path === "/api/me/config") {
    Object.assign(me, body);
    return me;
  }
  if (method === "GET" && path === "/api/me/chats") return chats;
  if (method === "GET" && path === "/api/me/waifu") return waifu;
  if (method === "POST" && path === "/api/me/divorce") {
    Object.assign(waifu, { is_married: false, married_waifu_id: null, married_waifu_name: null });
    Object.assign(me, { is_married: false, married_waifu_id: null, married_waifu_name: null });
    return waifu;
  }
  if (method === "GET" && path === "/api/me/gifts/catalog") return catalog;
  if (method === "GET" && path === "/api/me/gifts")
    return gifts.filter((gift) => gift.sent_to_bot === (url.searchParams.get("sent") === "true"));
  if (method === "POST" && path === "/api/me/gifts/buy") {
    const item = catalog.find((gift) => gift.gift_id === body.gift_id) ?? catalog[0];
    const gift = {
      ...item,
      ...{ id: Date.now(), rarity: 2, rarity_name: "珍稀", sent_to_bot: false, created_at: now },
    };
    gifts.push(gift);
    me.coins -= item.price;
    me.gift_count += 1;
    return gift;
  }
  if (method === "POST" && path === "/api/me/avatar/refresh") return { refreshed: true };
  if (method === "GET" && path === "/api/me/quotes") return page(quotes, url);
  if (method === "GET" && path === "/api/me/rss") return page(feeds, url);
  if (method === "POST" && path === "/api/me/rss") {
    const feed = {
      id: Date.now(),
      feed_id: Date.now(),
      url: body.url,
      title: "新的订阅",
      paused: false,
      interval_minutes: null,
      last_error: null,
      last_fetched_at: now,
      created_at: now,
    };
    feeds.push(feed);
    return feed;
  }
  if (method === "GET" && path === "/api/admin/stats") return stats;
  if (method === "GET" && path === "/api/admin/config")
    return {
      groups: { bot: { webapp: true, debug: false }, agent: { model: "kmua-cute-1" } },
      secrets: {},
      agent_providers: {},
      owners_count: 1,
    };
  if (method === "POST" && path === "/api/admin/config/reload")
    return { success: true, message: "演示配置已刷新", changed_fields: [] };
  if (method === "GET" && path === "/api/admin/chats")
    return page(
      chats.map((chat) => ({ ...chat, member_count: 886, created_at: now, is_blocked: false })),
      url,
    );
  if (method === "GET" && path === "/api/admin/users") return page(adminUsers, url);
  if (method === "GET" && path === "/api/admin/jobs")
    return [
      { id: "rss", name: "RSS 订阅轮询", trigger: "interval", next_run_time: now },
      { id: "daily", name: "每日元气任务", trigger: "cron", next_run_time: now },
    ];
  if (method === "GET" && path === "/api/admin/chat-policies")
    return { agent_whitelist_mode: false, rss_whitelist_mode: false, items: [] };
  if (method === "GET" && path === "/api/admin/agent-runs") return page([], url);

  let match = path.match(/^\/api\/me\/gifts\/(\d+)\/send$/);
  if (method === "POST" && match) {
    const gift = gifts.find((item) => item.id === Number(match[1]));
    if (gift) gift.sent_to_bot = true;
    return { gift, detail: "kmua 开心地收下了礼物，好感度上升啦！♡" };
  }
  match = path.match(/^\/api\/me\/rss\/(\d+)$/);
  if (match && method === "PATCH") {
    const feed = feeds.find((item) => item.feed_id === Number(match[1]));
    if (feed) Object.assign(feed, body);
    return feeds;
  }
  if (match && method === "DELETE") {
    const index = feeds.findIndex((item) => item.feed_id === Number(match[1]));
    if (index >= 0) feeds.splice(index, 1);
    return undefined;
  }
  if (
    (method === "DELETE" && path.startsWith("/api/me/quotes/")) ||
    (path.includes("/quotes/") && method === "DELETE")
  ) {
    const index = quotes.findIndex((quote) => path.endsWith(encodeURIComponent(quote.link)));
    if (index >= 0) quotes.splice(index, 1);
    return undefined;
  }

  match = path.match(/^\/api\/chats\/(-?\d+)$/);
  if (method === "GET" && match) return chatDetail(Number(match[1]));
  match = path.match(/^\/api\/chats\/(-?\d+)\/config$/);
  if (method === "PUT" && match) {
    Object.assign(config, body);
    return config;
  }
  match = path.match(/^\/api\/chats\/(-?\d+)\/title-permissions$/);
  if (method === "PUT" && match) {
    config.title_permissions = body.permissions;
    return config;
  }
  match = path.match(/^\/api\/chats\/(-?\d+)\/verify-questions$/);
  if (match && method === "GET") return { questions: config.verify_questions };
  if (match && method === "PUT") {
    config.verify_questions = body.questions;
    return { questions: config.verify_questions };
  }
  match = path.match(/^\/api\/chats\/(-?\d+)\/quotes$/);
  if (method === "GET" && match) {
    const query = (url.searchParams.get("q") ?? "").toLowerCase();
    return page(
      quotes.filter((quote) => !query || quote.text?.toLowerCase().includes(query)),
      url,
    );
  }
  match = path.match(/^\/api\/chats\/(-?\d+)\/rss$/);
  if (method === "GET" && match) return page(feeds, url);
  if (method === "POST" && match) {
    const feed = {
      id: Date.now(),
      feed_id: Date.now(),
      url: body.url,
      title: "新的群组订阅",
      paused: false,
      interval_minutes: null,
      last_error: null,
      last_fetched_at: now,
      created_at: now,
    };
    feeds.push(feed);
    return feed;
  }
  match = path.match(/^\/api\/chats\/(-?\d+)\/admins$/);
  if (method === "GET" && match)
    return [
      {
        user_id: 1,
        full_name: "小可爱",
        username: "kmua_fan",
        promoted_by: null,
        promoted_by_name: null,
      },
    ];
  match = path.match(/^\/api\/chats\/(-?\d+)\/sync-members$/);
  if (method === "POST" && match) return { removed: 3, checked: 886 };

  match = path.match(/^\/api\/admin\/chats\/(-?\d+)$/);
  if (method === "GET" && match) return chatDetail(Number(match[1]));
  match = path.match(/^\/api\/admin\/users\/(\d+)$/);
  if (match && method === "GET")
    return adminUsers.find((user) => user.id === Number(match[1])) ?? adminUsers[0];
  if (match && method === "PATCH") {
    const user = adminUsers.find((item) => item.id === Number(match[1])) ?? adminUsers[0];
    Object.assign(user, body);
    return { changed: [], skipped: [], user };
  }

  if (method === "DELETE") return undefined;
  if (method === "POST")
    return { success: true, refreshed: true, blocked: false, left: false, purged: false };
  return {};
}

export function installMockApi() {
  const originalFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.origin);
    if (!url.pathname.startsWith("/api/")) return originalFetch(input, init);
    await new Promise((resolve) => setTimeout(resolve, 120));
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    return json(respond(init.method ?? "GET", url.pathname, url, body));
  };
}
