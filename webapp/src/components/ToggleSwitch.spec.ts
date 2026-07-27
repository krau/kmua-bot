/**
 * Toggle tests.
 *
 * The switch is a real `<button role="switch">` rather than a styled div, and these
 * tests pin that: the role, the state announcement, and keyboard operation. If it ever
 * regresses to a div, this fails.
 */

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ToggleSwitch from "./ToggleSwitch.vue";

describe("ToggleSwitch", () => {
  it("renders as a switch with its state exposed", () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: true } });
    const button = wrapper.get("button");

    expect(button.attributes("role")).toBe("switch");
    expect(button.attributes("aria-checked")).toBe("true");
  });

  it("announces the off state", () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: false } });

    expect(wrapper.get("button").attributes("aria-checked")).toBe("false");
  });

  it("emits the inverted value on click", async () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: false } });

    await wrapper.get("button").trigger("click");

    expect(wrapper.emitted("update:modelValue")).toEqual([[true]]);
  });

  it("is operable from the keyboard", async () => {
    // A native button activates on Space and Enter without extra handlers; this
    // asserts the element really is a button rather than a div with a click listener.
    const wrapper = mount(ToggleSwitch, { props: { modelValue: false } });
    const button = wrapper.get("button");

    expect(button.element.tagName).toBe("BUTTON");
    expect(button.attributes("type")).toBe("button");
  });

  it("emits nothing while disabled", async () => {
    const wrapper = mount(ToggleSwitch, { props: { modelValue: false, disabled: true } });

    await wrapper.get("button").trigger("click");

    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
  });

  it("carries an accessible name when one is supplied", () => {
    const wrapper = mount(ToggleSwitch, {
      props: { modelValue: true, ariaLabel: "AI reply" },
    });

    expect(wrapper.get("button").attributes("aria-label")).toBe("AI reply");
  });
});
