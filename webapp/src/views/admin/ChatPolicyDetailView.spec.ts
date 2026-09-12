/**
 * Unmount behaviour of the chat-policy editor.
 *
 * The numeric fields are written through an 800ms debounce, and the unmount hook flushes
 * whatever is still queued. Removing the policy is the one case where there is nothing
 * left to write to, so the flush has to give up rather than enter its retry branch: the
 * retry re-arms itself for as long as an action is pending, and nothing can clear that
 * flag once the component is gone.
 */

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionStore } from "@/stores/session";
import { t } from "@/i18n";

import ChatPolicyDetailView from "./ChatPolicyDetailView.vue";

const { push, setChatPolicy, deleteChatPolicy, confirmMock } = vi.hoisted(() => ({
  push: vi.fn(),
  setChatPolicy: vi.fn(async () => ({})),
  deleteChatPolicy: vi.fn(async () => ({})),
  confirmMock: vi.fn(async () => true),
}));

vi.mock("vue-router", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/telegram", () => ({
  confirm: confirmMock,
  haptics: {
    tap: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));
vi.mock("@/api/endpoints/admin", () => ({
  fetchChatPolicy: vi.fn(async () => ({
    agent_whitelist_mode: true,
    rss_whitelist_mode: false,
    item: {
      chat_id: -1001,
      chat_title: "Chat",
      policy: {
        agent_allowed: true,
        rss_allowed: false,
        agent_quota_daily_tokens: 5,
        agent_quota_exempt: false,
      },
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      note: null,
    },
    agent_quota: {
      free_used_tokens_today: 0,
      free_limit_tokens: 5,
      credits: 0,
      requests_today: 0,
      input_tokens_today: 0,
      output_tokens_today: 0,
      exempt: false,
    },
  })),
  setChatPolicy,
  deleteChatPolicy,
}));

describe("ChatPolicyDetailView unmount", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    // Writes are owner-only in the UI, so the remove row only exists for an owner.
    useSessionStore().roles = ["owner"];
    setChatPolicy.mockClear();
    deleteChatPolicy.mockClear();
    confirmMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops the flush retry after the policy was removed with an edit still queued", async () => {
    const wrapper = mount(ChatPolicyDetailView, { props: { chatId: -1001 } });
    await vi.advanceTimersByTimeAsync(0);

    // Queue a numeric edit: this arms the 800ms debounce.
    wrapper.findAllComponents({ name: "NumberField" })[0]!.vm.$emit("update:modelValue", 7);
    // Remove before the debounce fires, so the edit is still queued at unmount.
    const removeRow = wrapper.findAll("button").find((button) => button.text().includes("移除"));
    expect(removeRow).toBeDefined();
    await removeRow!.trigger("click");
    await vi.advanceTimersByTimeAsync(0);

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(5_000);

    // A retry branch would have re-armed itself every 300ms for the whole 5s window and
    // still be armed; the notice's own dismiss timer does expire within it.
    expect(vi.getTimerCount()).toBe(0);
  });

  it("still flushes a queued edit when the view is left normally", async () => {
    const wrapper = mount(ChatPolicyDetailView, { props: { chatId: -1001 } });
    await vi.advanceTimersByTimeAsync(0);

    wrapper.findAllComponents({ name: "NumberField" })[0]!.vm.$emit("update:modelValue", 7);

    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(0);

    expect(setChatPolicy).toHaveBeenCalledWith(-1001, { agent_quota_daily_tokens: 7 });
  });
});

describe("ChatPolicyDetailView quota scope", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    useSessionStore().roles = ["owner"];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("offers the quota form for a group id", async () => {
    const wrapper = mount(ChatPolicyDetailView, { props: { chatId: -1001 } });
    await vi.advanceTimersByTimeAsync(0);

    expect(wrapper.text()).toContain(t("chatPolicy.quota"));
  });

  it("hides the quota form for a private chat id", async () => {
    // 群账户只在群里存在, 后端对私聊行的额度字段一律拒绝: 这里连入口都不该出现, 否则
    // 每一次改动都注定失败。
    const wrapper = mount(ChatPolicyDetailView, { props: { chatId: 12345 } });
    await vi.advanceTimersByTimeAsync(0);

    expect(wrapper.text()).not.toContain(t("chatPolicy.quota"));
    expect(wrapper.text()).not.toContain(t("chatPolicy.quotaUsage"));
  });
});
