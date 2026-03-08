import { expect, test, type Page } from "@playwright/test";

type DailyReviewResponse = {
  conversation_id: string;
  title: string;
  status: "existing" | "empty" | "ready";
};

type ConversationMessagesResponse = {
  conversation_id: string;
  messages: Array<{
    id: string;
    role: string;
    content: string;
  }>;
  total: number;
};

const DAILY_REVIEW_LABEL = "\u4eca\u65e5\u56de\u987e";
const REVIEW_SECTION_LABEL = "\u539f\u6587\u7247\u6bb5";
const EMPTY_STATE_LABEL = "\u4eca\u5929\u6ca1\u6709\u5230\u671f\u7684\u56de\u987e\u5185\u5bb9";
const BACKEND_BASE_URL = "http://localhost:8000";

function getTodayReviewTitle() {
  const today = new Date().toISOString().slice(0, 10);
  return `${DAILY_REVIEW_LABEL} ${today}`;
}

async function gotoHome(page: Page) {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3_000);
}

async function getDailyReviewButton(page: Page) {
  const button = page.locator("button").filter({ hasText: DAILY_REVIEW_LABEL }).last();
  await expect(button).toBeVisible();
  return button;
}

async function clickDailyReview(page: Page) {
  const button = await getDailyReviewButton(page);
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/review/daily")
      && response.request().method() === "POST",
  );

  await button.click();
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();

  return await response.json() as DailyReviewResponse;
}

test.describe("daily review", () => {
  test("opens today's review conversation through the real backend", async ({ page, request }) => {
    await gotoHome(page);

    const payload = await clickDailyReview(page);
    const expectedTitle = getTodayReviewTitle();

    expect(payload.title).toBe(expectedTitle);
    expect(["existing", "empty", "ready"]).toContain(payload.status);

    await expect(page.locator("body")).toContainText(expectedTitle);

    const bodyText = await page.locator("body").innerText();
    expect(
      bodyText.includes(REVIEW_SECTION_LABEL)
      || bodyText.includes(EMPTY_STATE_LABEL),
    ).toBeTruthy();

    const messagesResponse = await request.get(
      `${BACKEND_BASE_URL}/api/conversations/${payload.conversation_id}/messages?limit=20&offset=0`,
    );
    expect(messagesResponse.ok()).toBeTruthy();

    const messages = await messagesResponse.json() as ConversationMessagesResponse;
    expect(messages.conversation_id).toBe(payload.conversation_id);
    expect(messages.total).toBeGreaterThan(0);
    expect(messages.messages.some((message) => message.content.includes(expectedTitle))).toBeTruthy();
  });

  test("reuses the same daily review conversation on a second click", async ({ page }) => {
    await gotoHome(page);

    const firstPayload = await clickDailyReview(page);
    const secondPayload = await clickDailyReview(page);

    expect(secondPayload.status).toBe("existing");
    expect(secondPayload.title).toBe(firstPayload.title);
    expect(secondPayload.conversation_id).toBe(firstPayload.conversation_id);

    await expect(page.locator("body")).toContainText(firstPayload.title);
  });
});
