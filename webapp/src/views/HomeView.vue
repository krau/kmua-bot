<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import {
  ArrowRight,
  Cat,
  Flower2,
  Heart,
  Music2,
  SlidersHorizontal,
  Sparkles,
  UsersRound,
} from "@lucide/vue";

import mascotUrl from "@/assets/kmua-mascot.jpg";
import KmuaMark from "@/components/KmuaMark.vue";
import { t } from "@/i18n";
import { useMeStore } from "@/stores/me";
import { useSessionStore } from "@/stores/session";

const router = useRouter();
const session = useSessionStore();
const meStore = useMeStore();

const chatCount = computed(() => meStore.me?.chat_count ?? 0);

function open(routeName: string): void {
  void router.push({ name: routeName });
}
</script>

<template>
  <main class="home">
    <Sparkles
      class="home__orbit home__orbit--one"
      :size="28"
      :stroke-width="1.5"
      aria-hidden="true"
    />
    <Flower2
      class="home__orbit home__orbit--two"
      :size="24"
      :stroke-width="1.5"
      aria-hidden="true"
    />

    <section class="hero">
      <div class="hero__copy">
        <div class="brand"><KmuaMark /><span>kmua</span><i>bot</i></div>
        <div class="hero__status">{{ t("home.subtitle") }}</div>
        <h1>
          {{ t("home.heroTitle") }}<Music2 :size="28" :stroke-width="1.5" aria-hidden="true" />
        </h1>
        <p>{{ t("home.welcome") }}</p>
      </div>

      <div class="hero__art">
        <Sparkles
          class="hero__doodle hero__doodle--star"
          :size="32"
          :stroke-width="1.5"
          aria-hidden="true"
        />
        <Heart
          class="hero__doodle hero__doodle--heart"
          :size="24"
          :stroke-width="1.5"
          aria-hidden="true"
        />
        <div class="hero__bubble">{{ t("home.mascotHello") }}</div>
        <div class="hero__portrait">
          <img :src="mascotUrl" :alt="t('home.mascotAlt')" />
        </div>
        <div class="hero__name">{{ t("home.mascotTag") }}</div>
      </div>
    </section>

    <div class="home__divider">
      <Sparkles :size="14" :stroke-width="1.5" aria-hidden="true" />
      {{ t("home.choose") }}
      <Sparkles :size="14" :stroke-width="1.5" aria-hidden="true" />
    </div>

    <nav class="portal-list" :aria-label="t('home.choose')">
      <button type="button" class="portal portal--pink" @click="open('me')">
        <span class="portal__icon" aria-hidden="true">
          <Cat :size="34" :stroke-width="1.5" />
        </span>
        <span class="portal__text"
          ><strong>{{ t("home.me") }}</strong
          ><small>{{ t("home.meHint") }}</small></span
        >
        <span class="portal__sticker">{{ t("home.meSticker") }}</span>
        <ArrowRight class="portal__arrow" :size="22" :stroke-width="1.5" aria-hidden="true" />
      </button>

      <button type="button" class="portal portal--mint" @click="open('chats')">
        <span class="portal__icon" aria-hidden="true">
          <UsersRound :size="34" :stroke-width="1.5" />
        </span>
        <span class="portal__text"
          ><strong>{{ t("home.chats") }}</strong
          ><small>{{ t("home.chatsHint") }}</small></span
        >
        <span v-if="chatCount" class="portal__count">{{
          t("home.chatCount", { count: chatCount })
        }}</span>
        <ArrowRight class="portal__arrow" :size="22" :stroke-width="1.5" aria-hidden="true" />
      </button>

      <button
        v-if="session.isBotAdmin"
        type="button"
        class="portal portal--yellow"
        @click="open('admin')"
      >
        <span class="portal__icon" aria-hidden="true">
          <SlidersHorizontal :size="32" :stroke-width="1.5" />
        </span>
        <span class="portal__text"
          ><strong>{{ t("home.admin") }}</strong
          ><small>{{ t("home.adminHint") }}</small></span
        >
        <ArrowRight class="portal__arrow" :size="22" :stroke-width="1.5" aria-hidden="true" />
      </button>
    </nav>
  </main>
</template>

<style scoped>
.home {
  position: relative;
}

.home__orbit {
  position: absolute;
  z-index: -1;
  color: var(--kmua-pink);
  pointer-events: none;
}

.home__orbit--one {
  top: 1rem;
  right: 0;
  font-size: 1.75rem;
  rotate: 15deg;
}
.home__orbit--two {
  top: 15rem;
  left: 0;
  color: var(--kmua-mint);
  font-size: 1.5rem;
}

.hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(13rem, 0.85fr);
  align-items: center;
  min-height: 21rem;
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 75%);
  border-radius: 2rem 2rem 2rem 0.75rem;
  background:
    radial-gradient(circle at 18% 20%, rgb(255 255 255 / 85%) 0 2px, transparent 3px),
    radial-gradient(circle at 75% 18%, rgb(255 255 255 / 70%) 0 2px, transparent 3px),
    linear-gradient(125deg, var(--kmua-pink-soft), #fff7e9 54%, var(--kmua-mint-soft));
  background-size:
    42px 42px,
    56px 56px,
    auto;
  box-shadow: var(--kmua-shadow);
}

.hero__copy {
  position: relative;
  z-index: 2;
  padding: 2rem 0 2rem 2.25rem;
}

.brand {
  display: flex;
  align-items: center;
  color: var(--kmua-pink);
}
.brand svg {
  width: 2.75rem;
  margin-right: 0.35rem;
}
.brand > span {
  color: var(--kmua-ink);
  font-size: 1.7rem;
  font-weight: 600;
  letter-spacing: -0.06em;
}
.brand i {
  align-self: flex-start;
  margin: 0.4rem 0 0 0.4rem;
  padding: 0.05rem 0.4rem;
  border-radius: 0.4rem;
  background: var(--kmua-mint);
  color: #345e53;
  font-size: 0.625rem;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  rotate: 6deg;
}

.hero__status {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 1.4rem;
  color: var(--kmua-mint-dark);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.07em;
}

.hero h1 {
  max-width: 23rem;
  margin: 0.35rem 0 0.5rem;
  font-family: var(--font-display);
  font-size: clamp(2rem, 5vw, 2.85rem);
  font-weight: 400;
  line-height: 1.3;
  letter-spacing: 0.015em;
}

.hero h1 svg {
  position: absolute;
  margin: 0.2rem 0 0 0.2rem;
  color: var(--kmua-pink);
  rotate: 12deg;
}
.hero__copy > p {
  margin: 0;
  color: var(--kmua-hint);
  font-size: 0.875rem;
}
.hero__art {
  position: relative;
  align-self: stretch;
  min-height: 20rem;
}
.hero__portrait {
  position: absolute;
  right: 1.25rem;
  bottom: -1.5rem;
  width: min(16rem, 100%);
  aspect-ratio: 1;
  overflow: hidden;
  border: 6px solid rgb(255 255 255 / 80%);
  border-radius: 48% 48% 40% 52%;
  rotate: 4deg;
  box-shadow: 0 10px 30px rgb(113 76 91 / 16%);
  animation: mascot-float 4s ease-in-out infinite;
}

.hero__portrait::after {
  position: absolute;
  inset: 0;
  background: linear-gradient(to top, rgb(255 220 225 / 20%), transparent 45%);
  content: "";
}

.hero__portrait img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  scale: 1.04;
}
.hero__bubble {
  position: absolute;
  top: 1.5rem;
  right: 1.5rem;
  z-index: 2;
  padding: 0.45rem 0.8rem;
  border: 2px solid var(--kmua-pink);
  border-radius: 1rem 1rem 0.2rem 1rem;
  background: var(--kmua-surface);
  color: var(--kmua-ink);
  font-size: 0.75rem;
  font-weight: 600;
  rotate: 5deg;
}

.hero__name {
  position: absolute;
  right: 1.5rem;
  bottom: 1rem;
  z-index: 3;
  padding: 0.35rem 0.8rem;
  border-radius: 0.75rem;
  background: var(--kmua-surface);
  color: var(--kmua-hint);
  font-size: 0.625rem;
  font-weight: 600;
  box-shadow: 0 3px 10px rgb(80 50 60 / 10%);
  rotate: -3deg;
}

.hero__doodle {
  position: absolute;
  z-index: 2;
  color: var(--kmua-pink);
}
.hero__doodle--star {
  top: 5rem;
  left: 0;
  font-size: 2rem;
  animation: twinkle 2.5s ease-in-out infinite;
}
.hero__doodle--heart {
  right: 0.75rem;
  top: 6rem;
  color: var(--kmua-mint-dark);
  font-size: 1.5rem;
  rotate: 20deg;
}

.home__divider {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.65rem;
  margin: 1.75rem 0 1rem;
  color: var(--kmua-hint);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.home__divider svg {
  color: var(--kmua-yellow);
  font-size: 0.625rem;
}
.portal-list {
  display: grid;
  gap: 0.875rem;
}
.portal {
  position: relative;
  display: flex;
  align-items: center;
  gap: 1rem;
  width: 100%;
  min-height: 6.25rem;
  padding: 1rem 1.25rem;
  overflow: hidden;
  border: 1px solid var(--kmua-line);
  border-radius: 1.5rem;
  background: var(--kmua-surface);
  text-align: left;
  box-shadow: 0 4px 0 color-mix(in srgb, var(--kmua-line) 70%, transparent);
  transition:
    translate 180ms ease,
    box-shadow 180ms ease,
    border-color 180ms ease;
}

.portal::after {
  position: absolute;
  right: -1.5rem;
  width: 6rem;
  height: 6rem;
  border: 1.5rem solid var(--portal-soft);
  border-radius: 50%;
  content: "";
  opacity: 0.7;
}

.portal:hover {
  translate: 0 -3px;
  border-color: var(--portal-color);
  box-shadow: 0 7px 0 var(--portal-soft);
}
.portal:active {
  translate: 0 2px;
  box-shadow: 0 1px 0 var(--portal-soft);
}
.portal--pink {
  --portal-color: var(--kmua-pink);
  --portal-soft: var(--kmua-pink-soft);
}
.portal--mint {
  --portal-color: var(--kmua-mint);
  --portal-soft: var(--kmua-mint-soft);
}
.portal--yellow {
  --portal-color: var(--kmua-yellow);
  --portal-soft: var(--kmua-yellow-soft);
}

.portal__icon {
  display: grid;
  flex: 0 0 auto;
  width: 3.75rem;
  height: 3.75rem;
  place-items: center;
  border-radius: 1.25rem 1.25rem 1.25rem 0.45rem;
  background: var(--portal-soft);
  color: var(--portal-color);
  rotate: -4deg;
  transition: rotate 180ms ease;
}

.portal:nth-child(even) .portal__icon {
  border-radius: 1.25rem 1.25rem 0.45rem 1.25rem;
  rotate: 4deg;
}
.portal:hover .portal__icon {
  rotate: 5deg;
}
.portal__icon svg {
  width: 2.75rem;
}
.portal__text {
  position: relative;
  z-index: 1;
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}
.portal__text strong {
  font-size: 1.0625rem;
  font-weight: 600;
}
.portal__text small {
  margin-top: 0.2rem;
  overflow: hidden;
  color: var(--kmua-hint);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.portal__arrow {
  position: relative;
  z-index: 1;
  color: var(--portal-color);
  font-size: 1.5rem;
  font-weight: 600;
  transition: translate 180ms ease;
}
.portal:hover .portal__arrow {
  translate: 3px 0;
}
.portal__sticker,
.portal__count {
  position: absolute;
  top: 0.5rem;
  right: 3.25rem;
  z-index: 2;
  padding: 0.1rem 0.45rem;
  border-radius: 0.4rem;
  background: var(--portal-soft);
  color: var(--kmua-hint);
  font-size: 0.5625rem;
  font-weight: 600;
  rotate: 4deg;
}

@keyframes mascot-float {
  0%,
  100% {
    translate: 0 0;
  }
  50% {
    translate: 0 -6px;
  }
}

@keyframes twinkle {
  0%,
  100% {
    opacity: 0.5;
    scale: 0.85;
  }
  50% {
    opacity: 1;
    scale: 1.1;
  }
}

@media (max-width: 560px) {
  .hero {
    grid-template-columns: minmax(0, 1.1fr) minmax(8.5rem, 0.9fr);
    min-height: 18rem;
    border-radius: 1.5rem 1.5rem 1.5rem 0.6rem;
  }
  .hero__copy {
    padding: 1.5rem 0 1.5rem 1.25rem;
  }
  .brand svg {
    width: 2.25rem;
  }
  .brand > span {
    font-size: 1.5rem;
  }
  .hero__status {
    margin-top: 1.25rem;
    font-size: 0.5625rem;
  }
  .hero h1 {
    font-size: clamp(1.65rem, 7vw, 2.25rem);
  }
  .hero__copy > p {
    max-width: 11rem;
    font-size: 0.75rem;
    line-height: 1.6;
  }
  .hero__art {
    min-height: 18rem;
  }
  .hero__portrait {
    right: 0.5rem;
    bottom: 0.5rem;
    width: 10.5rem;
    border-width: 4px;
  }
  .hero__bubble {
    top: 1.5rem;
    right: 0.75rem;
    padding: 0.35rem 0.55rem;
    font-size: 0.625rem;
  }
  .hero__name {
    right: 0.6rem;
    bottom: 0.5rem;
    white-space: nowrap;
  }
  .hero__doodle--star {
    left: -0.5rem;
  }
  .portal {
    min-height: 5.75rem;
    padding: 0.875rem 1rem;
    gap: 0.8rem;
  }
  .portal__icon {
    width: 3.25rem;
    height: 3.25rem;
    border-radius: 1rem;
  }
  .portal__icon svg {
    width: 2.4rem;
  }
  .portal__text small {
    max-width: 13rem;
  }
  .portal__sticker {
    display: none;
  }
  .portal__count {
    right: 2.5rem;
  }
}

@media (max-width: 360px) {
  .hero {
    grid-template-columns: 1fr;
  }
  .hero__copy {
    z-index: 2;
    padding-right: 1rem;
  }
  .hero__art {
    position: absolute;
    inset: 0 0 0 auto;
    width: 45%;
    opacity: 0.65;
  }
  .hero__copy > p {
    max-width: 10rem;
  }
  .portal__text small {
    max-width: 10rem;
  }
}
</style>

<style>
[data-theme="dark"] .home .hero {
  border-color: var(--kmua-line);
  background: linear-gradient(125deg, var(--kmua-pink-soft), #403846 54%, var(--kmua-mint-soft));
}
</style>
