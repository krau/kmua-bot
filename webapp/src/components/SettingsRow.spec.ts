/**
 * Settings row tests.
 *
 * Focused on the busy state, which exists because slow actions - refreshing an avatar,
 * syncing a member roster - previously looked like nothing had happened until the notice
 * arrived seconds later, so people tapped again. The row must therefore both show that
 * it is working and refuse a second tap while it is.
 */

import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import SettingsRow from "./SettingsRow.vue";

vi.mock("@/telegram", () => ({ haptics: { tap: vi.fn() } }));

describe("SettingsRow", () => {
  it("is a static div until it has something to do", () => {
    const wrapper = mount(SettingsRow, { props: { label: "喵喵币", value: 42 } });

    expect(wrapper.element.tagName).toBe("DIV");
  });

  it("is a real button when it acts", () => {
    const wrapper = mount(SettingsRow, { props: { label: "刷新头像", navigable: true } });
    const button = wrapper.get("button");

    expect(button.attributes("type")).toBe("button");
  });

  it("emits a click when tapped", async () => {
    const wrapper = mount(SettingsRow, { props: { label: "刷新头像", navigable: true } });

    await wrapper.get("button").trigger("click");

    expect(wrapper.emitted("click")).toHaveLength(1);
  });

  it("shows a spinner and announces itself while busy", () => {
    const wrapper = mount(SettingsRow, {
      props: { label: "刷新头像", navigable: true, busy: true },
    });

    expect(wrapper.get("button").attributes("aria-busy")).toBe("true");
    expect(wrapper.find(".activity-dot").exists()).toBe(true);
  });

  it("shows no spinner when idle", () => {
    const wrapper = mount(SettingsRow, { props: { label: "刷新头像", navigable: true } });

    expect(wrapper.get("button").attributes("aria-busy")).toBeUndefined();
    expect(wrapper.find(".activity-dot").exists()).toBe(false);
  });

  it("refuses a second tap while busy", async () => {
    const wrapper = mount(SettingsRow, {
      props: { label: "刷新头像", navigable: true, busy: true },
    });

    await wrapper.get("button").trigger("click");

    expect(wrapper.emitted("click")).toBeUndefined();
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
  });

  it("swaps the chevron for the spinner rather than showing both", () => {
    const idle = mount(SettingsRow, { props: { label: "同步成员", navigable: true } });
    expect(idle.text()).toContain("›");

    const busy = mount(SettingsRow, {
      props: { label: "同步成员", navigable: true, busy: true },
    });
    expect(busy.text()).not.toContain("›");
  });

  it("hides a stale value while the action that replaces it is running", () => {
    // The member count is about to change, so showing the old one beside a spinner
    // would assert something that is in the middle of becoming false.
    const wrapper = mount(SettingsRow, {
      props: { label: "同步成员", value: 128, navigable: true, busy: true },
    });

    expect(wrapper.text()).not.toContain("128");
  });

  it("stays at full opacity while busy, but dims when disabled", () => {
    const busy = mount(SettingsRow, {
      props: { label: "刷新头像", navigable: true, busy: true },
    });
    expect(busy.get("button").classes()).not.toContain("opacity-50");

    const disabled = mount(SettingsRow, {
      props: { label: "刷新头像", navigable: true, disabled: true },
    });
    expect(disabled.get("button").classes()).toContain("opacity-50");
  });

  it("emits nothing from a static row", async () => {
    const wrapper = mount(SettingsRow, { props: { label: "ID", value: 555 } });

    await wrapper.trigger("click");

    expect(wrapper.emitted("click")).toBeUndefined();
  });
});
