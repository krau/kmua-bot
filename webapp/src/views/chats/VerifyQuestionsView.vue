<script setup lang="ts">
/**
 * A group's custom question bank for the "custom Q&A" verification method.
 *
 * Two levels: a compact list of all questions (meta line + inline delete), and a
 * per-question editor opened by tapping a row (question text, editable option
 * rows with inline toggles marking correct answers - multi-select allowed).
 * Empty option rows are dropped on save. The API replaces the whole set on save,
 * so what is on screen is exactly what gets saved.
 */
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { fetchVerifyQuestions, saveVerifyQuestions } from "@/api/endpoints/chats";
import { isApiError } from "@/api/errors";
import type { VerifyQuestion } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDirtyState } from "@/composables/useDirtyState";
import { useMainButton } from "@/composables/useMainButton";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { haptics } from "@/telegram";

const props = defineProps<{ chatId: number }>();

const MAX_QUESTIONS = 200;
const MAX_OPTIONS = 6;
/** 新建题目时预置的空选项行数(2 是后端下限, 多给一行方便起步)。 */
const INITIAL_OPTION_ROWS = 3;

/** Draft shape: options are editable rows, each carrying its own correct flag. */
interface OptionRow {
  text: string;
  correct: boolean;
}

interface QuestionDraft {
  question: string;
  optionRows: OptionRow[];
  /** 多正确答案时: true = 任选其一即可, false = 必须全选。 */
  anyOf: boolean;
}

function toDraft(question: VerifyQuestion): QuestionDraft {
  return {
    question: question.question,
    optionRows: question.options.map((text) => ({
      text,
      correct: question.answers.includes(text),
    })),
    anyOf: question.select === "any",
  };
}

function toPayload(draft: QuestionDraft): VerifyQuestion {
  const options: string[] = [];
  const answers: string[] = [];
  for (const row of draft.optionRows) {
    const text = row.text.trim();
    if (!text || options.includes(text)) continue;
    options.push(text);
    if (row.correct) answers.push(text);
  }
  return {
    question: draft.question,
    options,
    // 一个都没勾时默认第一个选项为正确答案; 单选时模式恒为 all。
    answers: answers.length > 0 ? answers : [options[0] ?? ""],
    select: answers.length > 1 && draft.anyOf ? "any" : "all",
  };
}

/** 列表行的摘要: 非空选项数 + 正确答案内容(逗号拼接, 展示层截断)。 */
function questionMeta(question: QuestionDraft): { options: number; correct: string } {
  const rows = question.optionRows.filter((row) => row.text.trim().length > 0);
  const answers = rows.filter((row) => row.correct).map((row) => row.text.trim());
  return { options: rows.length, correct: answers.join(", ") };
}

function correctCount(question: QuestionDraft): number {
  return question.optionRows.filter((row) => row.text.trim().length > 0 && row.correct).length;
}

const saving = ref(false);
const route = useRoute();
const router = useRouter();
/** 当前编辑的题目下标; 由路由 query 驱动, 原生返回键即可回到列表。 */
const editingIndex = computed<number | null>(() => {
  const raw = route.query.edit;
  if (typeof raw !== "string" || !/^\d+$/.test(raw)) return null;
  const index = Number(raw);
  return index >= 0 && index < form.draft.value.questions.length ? index : null;
});
/** 正在编辑的题目草稿(列表模式下为 undefined)。 */
const editingQuestion = computed<QuestionDraft | undefined>(() =>
  editingIndex.value === null ? undefined : form.draft.value.questions[editingIndex.value],
);
const { notify, notifyError } = useNotice();

const form = useDirtyState<{ questions: QuestionDraft[] }>({ questions: [] });

const data = useAsyncData(async (signal) => {
  const result = await fetchVerifyQuestions(props.chatId, signal);
  form.commit({ questions: result.questions.map(toDraft) });
  return result;
});

const canAdd = computed(() => form.draft.value.questions.length < MAX_QUESTIONS);

function openQuestion(index: number): void {
  void router.push({ query: { edit: String(index) } });
}

function closeEditor(): void {
  void router.replace({ query: {} });
}

function addQuestion(): void {
  if (!canAdd.value) return;
  form.draft.value.questions.push({
    question: "",
    optionRows: Array.from({ length: INITIAL_OPTION_ROWS }, () => ({
      text: "",
      correct: false,
    })),
    anyOf: false,
  });
  openQuestion(form.draft.value.questions.length - 1);
}

function addOption(question: QuestionDraft): void {
  if (question.optionRows.length < MAX_OPTIONS) {
    question.optionRows.push({ text: "", correct: false });
  }
}

function removeQuestion(index: number): void {
  // Plain removal: nothing is saved yet, reset can bring it back.
  form.draft.value.questions.splice(index, 1);
  if (editingIndex.value === index) {
    closeEditor();
  }
}

function removeEditingQuestion(): void {
  if (editingIndex.value !== null) {
    removeQuestion(editingIndex.value);
  }
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    const saved = await saveVerifyQuestions(
      props.chatId,
      form.draft.value.questions.map(toPayload),
    );
    form.commit({ questions: saved.questions.map(toDraft) });
    closeEditor();
    notify(t("app.saved"));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    saving.value = false;
  }
}

useMainButton({
  text: () => t("app.saveCount", { count: form.changedFields.value.length }),
  visible: () => form.isDirty.value,
  enabled: () => form.isDirty.value && !saving.value,
  loading: () => saving.value,
  onClick: () => void save(),
  secondary: {
    text: () => t("app.reset"),
    visible: () => form.isDirty.value,
    onClick: () => form.reset(),
  },
});
</script>

<template>
  <PageHeader :title="t('chats.verifyQuestions')" :subtitle="t('chats.verifyQuestionsHint')" />

  <StateBlock
    :loading="data.loading.value && !data.data.value"
    :error="data.error.value"
    @retry="data.reload"
  >
    <!-- 列表模式: 每行一道题的摘要, 行内可删除 -->
    <template v-if="editingIndex === null">
      <SettingsSection :label="t('chats.verifyListLabel')">
        <div
          v-for="(question, index) in form.draft.value.questions"
          :key="index"
          class="border-line flex items-center gap-related border-b px-related py-related last:border-b-0"
        >
          <button
            type="button"
            class="min-w-0 flex-1 cursor-pointer text-left"
            @click="openQuestion(index)"
          >
            <span class="block truncate text-body">
              {{ question.question.trim() || t("chats.verifyUntitled") }}
            </span>
            <span class="mt-1 block truncate text-note text-hint">
              {{
                t("chats.verifyQuestionMeta", {
                  options: questionMeta(question).options,
                  correct: questionMeta(question).correct || t("chats.verifyCorrectNone"),
                })
              }}{{ question.anyOf ? " · " + t("chats.verifyAnyOf") : "" }}
            </span>
          </button>
          <button
            type="button"
            class="shrink-0 cursor-pointer px-2 text-sub text-danger dark:text-danger-dark"
            :aria-label="t('chats.verifyDelete')"
            @click="removeQuestion(index)"
          >
            {{ t("chats.verifyDelete") }}
          </button>
        </div>
        <SettingsRow
          v-if="form.draft.value.questions.length === 0"
          :label="t('chats.verifyEmpty')"
          :hint="t('chats.verifyEmptyHint')"
        />
      </SettingsSection>

      <SettingsSection>
        <SettingsRow
          :label="t('chats.verifyAddQuestion')"
          navigable
          :disabled="!canAdd"
          @click="addQuestion"
        />
      </SettingsSection>
    </template>

    <!-- 详情模式: 单题编辑 -->
    <template v-else-if="editingQuestion">
      <SettingsSection
        :label="t('chats.verifyQuestionNumber', { number: (editingIndex ?? 0) + 1 })"
      >
        <TextField
          v-model="editingQuestion.question"
          :label="t('chats.verifyQuestionPrompt')"
          :maxlength="200"
        />
        <SettingsRow :label="t('chats.verifyOptions')" :hint="t('chats.verifyOptionsHint')" />
        <div
          v-for="(option, optionIndex) in editingQuestion.optionRows"
          :key="optionIndex"
          class="border-line flex items-center gap-related border-b px-related py-related last:border-b-0"
        >
          <input
            v-model="option.text"
            type="text"
            :maxlength="100"
            :placeholder="t('chats.verifyOptionPlaceholder', { number: optionIndex + 1 })"
            :aria-label="t('chats.verifyOptionPlaceholder', { number: optionIndex + 1 })"
            class="field-input min-w-0 flex-1 text-body"
          />
          <ToggleSwitch v-model="option.correct" :aria-label="t('chats.verifyCorrectAnswer')" />
        </div>
        <SettingsRow
          v-if="correctCount(editingQuestion) >= 2"
          :label="t('chats.verifyAnyOf')"
          :hint="t('chats.verifyAnyOfHint')"
        >
          <template #control>
            <ToggleSwitch v-model="editingQuestion.anyOf" :aria-label="t('chats.verifyAnyOf')" />
          </template>
        </SettingsRow>
        <SettingsRow
          :label="t('chats.verifyAddOption')"
          navigable
          :disabled="editingQuestion.optionRows.length >= MAX_OPTIONS"
          @click="addOption(editingQuestion)"
        />
        <SettingsRow
          :label="t('chats.verifyRemoveQuestion')"
          navigable
          destructive
          @click="removeEditingQuestion"
        />
      </SettingsSection>
    </template>
  </StateBlock>
</template>
