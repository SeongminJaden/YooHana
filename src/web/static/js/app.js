/* ═══════════════════════════════════════════════════════
   AI Influencer — Frontend Logic
   ═══════════════════════════════════════════════════════ */

(function () {
  "use strict";

  // ── DOM References ─────────────────────────────────────

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const postGrid = $("#postGrid");
  const emptyState = $("#emptyState");
  const postCount = $("#postCount");

  // Tabs
  const tabs = $$(".tab");
  const tabContents = $$(".tab-content");

  // Chat
  const chatMessages = $("#chatMessages");
  const chatInput = $("#chatInput");
  const chatSend = $("#chatSend");

  // Post form
  const sourceBtns = $$(".source-btn");
  const uploadSection = $("#uploadSection");
  const aiSection = $("#aiSection");
  const previewSection = $("#previewSection");
  const previewImg = $("#previewImg");
  const removeImage = $("#removeImage");
  const imageFile = $("#imageFile");
  const aiPrompt = $("#aiPrompt");
  const generateImageBtn = $("#generateImage");
  const captionText = $("#captionText");
  const captionTopic = $("#captionTopic");
  const generateCaptionBtn = $("#generateCaption");
  const hashtagText = $("#hashtagText");
  const generateHashtagsBtn = $("#generateHashtags");
  const savePostBtn = $("#savePost");
  const postInstagramBtn = $("#postInstagram");

  // Modal
  const postModal = $("#postModal");
  const modalClose = $("#modalClose");
  const modalImg = $("#modalImg");
  const modalCaption = $("#modalCaption");
  const modalHashtags = $("#modalHashtags");
  const modalDate = $("#modalDate");
  const modalStatus = $("#modalStatus");
  const modalDelete = $("#modalDelete");

  // Loading
  const loadingOverlay = $("#loadingOverlay");
  const loadingText = $("#loadingText");

  // ── State ──────────────────────────────────────────────

  let currentFilename = "";
  let currentSource = "upload";
  let currentModalPostId = "";
  let chatHistory = []; // {role: "user"|"bot", text: "..."}

  // ── Helpers ────────────────────────────────────────────

  function showLoading(text) {
    loadingText.textContent = text || "처리 중...";
    loadingOverlay.classList.remove("hidden");
  }

  function hideLoading() {
    loadingOverlay.classList.add("hidden");
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, opts);
    return res.json();
  }

  async function apiPost(url, body) {
    return api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${y}.${m}.${day} ${h}:${min}`;
  }

  // ── Tabs ───────────────────────────────────────────────

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tabContents.forEach((tc) => tc.classList.remove("active"));
      tab.classList.add("active");
      const target = tab.dataset.tab;
      $(`#tab-${target}`).classList.add("active");
    });
  });

  // ── Chat ───────────────────────────────────────────────

  function appendMessage(role, text) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "msg-avatar";
    avatar.textContent = role === "bot" ? "하나" : "나";

    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.textContent = text;

    div.appendChild(avatar);
    div.appendChild(bubble);
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  async function sendChat() {
    const msg = chatInput.value.trim();
    if (!msg) return;

    chatInput.value = "";
    chatSend.disabled = true;
    appendMessage("user", msg);
    chatHistory.push({ role: "user", text: msg });

    try {
      const data = await apiPost("/api/chat", {
        message: msg,
        history: chatHistory.slice(-10), // last 10 turns (5 pairs)
      });
      if (data.error) {
        appendMessage("bot", `오류: ${data.error}`);
      } else {
        appendMessage("bot", data.reply);
        chatHistory.push({ role: "bot", text: data.reply });
      }
    } catch (e) {
      appendMessage("bot", "서버 연결 오류가 발생했어요 😢");
    } finally {
      chatSend.disabled = false;
      chatInput.focus();
    }
  }

  chatSend.addEventListener("click", sendChat);
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  });

  // ── Source Toggle ──────────────────────────────────────

  sourceBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      sourceBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentSource = btn.dataset.source;

      if (currentSource === "upload") {
        uploadSection.classList.remove("hidden");
        aiSection.classList.add("hidden");
      } else {
        uploadSection.classList.add("hidden");
        aiSection.classList.remove("hidden");
      }
    });
  });

  // ── Image Upload ───────────────────────────────────────

  imageFile.addEventListener("change", async () => {
    const file = imageFile.files[0];
    if (!file) return;

    showLoading("이미지 업로드 중...");

    const formData = new FormData();
    formData.append("image", file);

    try {
      const data = await api("/api/upload-image", {
        method: "POST",
        body: formData,
      });

      if (data.error) {
        alert(`업로드 실패: ${data.error}`);
      } else {
        currentFilename = data.filename;
        previewImg.src = data.url;
        previewSection.classList.remove("hidden");
      }
    } catch (e) {
      alert("업로드 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
    }
  });

  // ── Remove Image ───────────────────────────────────────

  removeImage.addEventListener("click", () => {
    currentFilename = "";
    previewImg.src = "";
    previewSection.classList.add("hidden");
    imageFile.value = "";
  });

  // ── AI Image Generation ────────────────────────────────

  generateImageBtn.addEventListener("click", async () => {
    const topic = aiPrompt.value.trim();
    if (!topic) {
      alert("이미지 주제를 입력해주세요.");
      return;
    }

    showLoading("AI 이미지 생성 중...");
    generateImageBtn.disabled = true;

    try {
      const data = await apiPost("/api/generate-image", { topic });
      if (data.error) {
        alert(`이미지 생성 실패: ${data.error}`);
      } else {
        currentFilename = data.filename;
        previewImg.src = data.url;
        previewSection.classList.remove("hidden");
      }
    } catch (e) {
      alert("이미지 생성 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
      generateImageBtn.disabled = false;
    }
  });

  // ── AI Caption Generation ──────────────────────────────

  generateCaptionBtn.addEventListener("click", async () => {
    const topic = captionTopic.value.trim() || "일상";
    showLoading("캡션 생성 중...");
    generateCaptionBtn.disabled = true;

    try {
      const data = await apiPost("/api/generate-caption", { topic });
      if (data.error) {
        alert(`캡션 생성 실패: ${data.error}`);
      } else {
        captionText.value = data.caption;
      }
    } catch (e) {
      alert("캡션 생성 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
      generateCaptionBtn.disabled = false;
    }
  });

  // ── AI Hashtag Generation ──────────────────────────────

  generateHashtagsBtn.addEventListener("click", async () => {
    const topic =
      captionTopic.value.trim() || captionText.value.trim().slice(0, 30) || "일상";
    showLoading("해시태그 생성 중...");
    generateHashtagsBtn.disabled = true;

    try {
      const data = await apiPost("/api/generate-hashtags", { topic });
      if (data.error) {
        alert(`해시태그 생성 실패: ${data.error}`);
      } else {
        hashtagText.value = data.hashtags;
      }
    } catch (e) {
      alert("해시태그 생성 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
      generateHashtagsBtn.disabled = false;
    }
  });

  // ── Save Post ──────────────────────────────────────────

  savePostBtn.addEventListener("click", async () => {
    if (!currentFilename) {
      alert("이미지를 먼저 업로드하거나 생성해주세요.");
      return;
    }

    showLoading("저장 중...");

    try {
      const data = await apiPost("/api/save-post", {
        filename: currentFilename,
        caption: captionText.value.trim(),
        hashtags: hashtagText.value.trim(),
        source: currentSource,
      });

      if (data.error) {
        alert(`저장 실패: ${data.error}`);
      } else {
        resetPostForm();
        loadPosts();
      }
    } catch (e) {
      alert("저장 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
    }
  });

  // ── Post to Instagram ──────────────────────────────────

  postInstagramBtn.addEventListener("click", async () => {
    if (!currentFilename) {
      alert("이미지를 먼저 업로드하거나 생성해주세요.");
      return;
    }

    if (!confirm("Instagram에 게시하시겠습니까?")) return;

    showLoading("게시물 저장 중...");

    try {
      // Save first
      const saveData = await apiPost("/api/save-post", {
        filename: currentFilename,
        caption: captionText.value.trim(),
        hashtags: hashtagText.value.trim(),
        source: currentSource,
      });

      if (saveData.error) {
        alert(`저장 실패: ${saveData.error}`);
        hideLoading();
        return;
      }

      showLoading("Instagram에 게시 중...");

      const postData = await apiPost("/api/post-instagram", {
        post_id: saveData.post.id,
      });

      if (postData.error) {
        alert(`게시 실패: ${postData.error}`);
      } else {
        alert("Instagram에 성공적으로 게시되었습니다!");
        resetPostForm();
      }

      loadPosts();
    } catch (e) {
      alert("게시 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
    }
  });

  // ── Reset Form ─────────────────────────────────────────

  function resetPostForm() {
    currentFilename = "";
    previewImg.src = "";
    previewSection.classList.add("hidden");
    imageFile.value = "";
    aiPrompt.value = "";
    captionText.value = "";
    captionTopic.value = "";
    hashtagText.value = "";
  }

  // ── Post Grid ──────────────────────────────────────────

  async function loadPosts() {
    try {
      const posts = await api("/api/posts");
      renderGrid(posts);
    } catch (e) {
      console.error("게시물 로드 실패:", e);
    }
  }

  function renderGrid(posts) {
    postCount.textContent = posts.length;

    // Clear grid except empty state
    postGrid.querySelectorAll(".grid-item").forEach((el) => el.remove());

    if (posts.length === 0) {
      emptyState.classList.remove("hidden");
      return;
    }

    emptyState.classList.add("hidden");

    posts.forEach((post) => {
      const item = document.createElement("div");
      item.className = "grid-item";
      item.addEventListener("click", () => openModal(post));

      const img = document.createElement("img");
      img.src = post.image_url;
      img.alt = post.caption || "";
      img.loading = "lazy";
      item.appendChild(img);

      if (post.posted) {
        const badge = document.createElement("span");
        badge.className = "posted-badge";
        badge.textContent = post.source === "bot" ? "자동" : post.source === "instagram" ? "IG" : "게시됨";
        item.appendChild(badge);
      }

      postGrid.appendChild(item);
    });
  }

  // ── Modal ──────────────────────────────────────────────

  function openModal(post) {
    currentModalPostId = post.id;
    modalImg.src = post.image_url;
    modalCaption.textContent = post.caption || "(캡션 없음)";
    modalHashtags.textContent = post.hashtags || "";
    modalDate.textContent = formatDate(post.created_at);

    if (post.posted) {
      const labels = { bot: "자동 게시됨", instagram: "Instagram 동기화", upload: "게시됨" };
      modalStatus.textContent = labels[post.source] || "게시됨";
      modalStatus.className = "modal-status posted";
    } else {
      modalStatus.textContent = "임시저장";
      modalStatus.className = "modal-status draft";
    }

    // Show permalink if available
    const existingLink = postModal.querySelector(".modal-permalink");
    if (existingLink) existingLink.remove();
    if (post.permalink) {
      const link = document.createElement("a");
      link.className = "modal-permalink";
      link.href = post.permalink;
      link.target = "_blank";
      link.textContent = "Instagram에서 보기";
      link.style.cssText = "font-size:13px;color:var(--accent);text-decoration:none;display:block;margin-top:8px;";
      $(".modal-info").querySelector(".modal-date").after(link);
    }

    postModal.classList.remove("hidden");
  }

  function closeModal() {
    postModal.classList.add("hidden");
    currentModalPostId = "";
  }

  modalClose.addEventListener("click", closeModal);

  postModal.addEventListener("click", (e) => {
    if (e.target === postModal) closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !postModal.classList.contains("hidden")) {
      closeModal();
    }
  });

  // ── Delete Post ────────────────────────────────────────

  modalDelete.addEventListener("click", async () => {
    if (!currentModalPostId) return;
    if (!confirm("이 게시물을 삭제하시겠습니까?")) return;

    try {
      await api(`/api/posts/${currentModalPostId}`, { method: "DELETE" });
      closeModal();
      loadPosts();
    } catch (e) {
      alert("삭제 중 오류가 발생했습니다.");
    }
  });

  // ── Sync Instagram ─────────────────────────────────────

  const syncBtn = $("#syncInstagram");
  if (syncBtn) {
    syncBtn.addEventListener("click", async () => {
      if (!confirm("Instagram에서 게시물을 가져오시겠습니까?\n(브라우저 로그인이 필요합니다)")) return;

      showLoading("Instagram 게시물 동기화 중...");
      syncBtn.disabled = true;

      try {
        const data = await apiPost("/api/sync-instagram", {});
        if (data.error) {
          alert(`동기화 실패: ${data.error}`);
        } else {
          alert(data.message);
          loadPosts();
        }
      } catch (e) {
        alert("동기화 중 오류가 발생했습니다.");
      } finally {
        hideLoading();
        syncBtn.disabled = false;
      }
    });
  }

  // ── Init ───────────────────────────────────────────────

  loadPosts();
})();
