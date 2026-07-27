/**
 * Notice banner tests.
 *
 * These pin the two properties that made the old inline line unusable: the bar is
 * fixed to the viewport rather than sitting in the page flow (so it stays visible when
 * scrolled, and its appearance shifts nothing), and the live region is always mounted
 * so a screen reader reliably announces text that appears later.
 */

import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import NoticeBanner from "./NoticeBanner.vue";
import { useNotice } from "@/composables/useNotice";

vi.mock("@/telegram", () => ({ haptics: { tap: vi.fn() } }));

const { notify, notifyError, dismiss } = useNotice();

afterEach(() => dismiss());

describe("NoticeBanner", () => {
  it("keeps the live region mounted with nothing to show", () => {
    const wrapper = mount(NoticeBanner);
    const region = wrapper.get('[role="status"]');

    expect(region.attributes("aria-live")).toBe("polite");
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("shows a posted notice", async () => {
    const wrapper = mount(NoticeBanner);
    notify("已保存");
    await wrapper.vm.$nextTick();

    expect(wrapper.get("button").text()).toBe("已保存");
  });

  it("marks a failure differently from a success", async () => {
    const wrapper = mount(NoticeBanner);

    notify("已保存");
    await wrapper.vm.$nextTick();
    expect(wrapper.get("button").classes()).toContain("notice-bar--success");

    notifyError("加载失败");
    await wrapper.vm.$nextTick();
    expect(wrapper.get("button").classes()).toContain("notice-bar--error");
  });

  it("dismisses when tapped", async () => {
    const wrapper = mount(NoticeBanner);
    notify("已保存");
    await wrapper.vm.$nextTick();

    await wrapper.get("button").trigger("click");

    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("is fixed to the viewport, so it neither scrolls away nor shifts the page", () => {
    const wrapper = mount(NoticeBanner);

    // Scoped styles are not applied in jsdom, so assert the class contract instead:
    // the region carries the positioning, the bar carries the appearance.
    expect(wrapper.get('[role="status"]').classes()).toContain("notice-region");
  });

  it("reuses one bar when notices arrive back to back", async () => {
    // The regression this guards: keying the bar by notice id made a replacement a
    // remove-plus-insert, so both transitions ran together and two bars overlapped and
    // displaced each other. Reusing the element is what keeps a rapid second save from
    // shoving the first banner around.
    const wrapper = mount(NoticeBanner);

    notify("已保存");
    await wrapper.vm.$nextTick();
    const first = wrapper.get("button").element;

    notify("头像已刷新");
    await wrapper.vm.$nextTick();

    expect(wrapper.findAll("button")).toHaveLength(1);
    expect(wrapper.get("button").element).toBe(first);
    expect(wrapper.get("button").text()).toBe("头像已刷新");
  });

  it("shows one bar when a success is replaced by a failure", async () => {
    const wrapper = mount(NoticeBanner);

    notify("已保存");
    await wrapper.vm.$nextTick();
    notifyError("加载失败");
    await wrapper.vm.$nextTick();

    const bars = wrapper.findAll("button");

    expect(bars).toHaveLength(1);
    expect(bars[0]?.classes()).toContain("notice-bar--error");
    expect(bars[0]?.classes()).not.toContain("notice-bar--success");
  });
});
