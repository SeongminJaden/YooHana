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
  const modalPost = $("#modalPost");

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

  // ── Auto Image Prompt from Caption ────────────────────

  const autoPromptBtn = $("#autoPrompt");
  autoPromptBtn.addEventListener("click", async () => {
    const caption = captionText.value.trim() || captionTopic.value.trim() || "일상";
    showLoading("프롬프트 생성 중...");
    try {
      const data = await apiPost("/api/generate-image-prompt", {
        caption,
        platform: "instagram",
      });
      if (data.error) {
        alert(data.error);
      } else {
        aiPrompt.value = data.prompt;
      }
    } catch (e) {
      alert("프롬프트 생성 오류");
    } finally {
      hideLoading();
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
      modalPost.style.display = "none";
    } else {
      modalStatus.textContent = "임시저장";
      modalStatus.className = "modal-status draft";
      modalPost.style.display = "";
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

  // ── Post from Modal ─────────────────────────────────────

  modalPost.addEventListener("click", async () => {
    if (!currentModalPostId) return;
    if (!confirm("이 게시물을 Instagram에 게시하시겠습니까?")) return;

    showLoading("Instagram에 게시 중...");
    modalPost.disabled = true;

    try {
      const data = await apiPost("/api/post-instagram", {
        post_id: currentModalPostId,
      });

      if (data.error) {
        alert(`게시 실패: ${data.error}`);
      } else {
        alert("Instagram에 성공적으로 게시되었습니다!");
        closeModal();
        loadPosts();
      }
    } catch (e) {
      alert("게시 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
      modalPost.disabled = false;
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

  // ── Comments Tab ───────────────────────────────────────

  const commentList = $("#commentList");
  const commentEmptyState = $("#commentEmptyState");
  const commentCountBadge = $("#commentCountBadge");
  const scanCommentsBtn = $("#scanComments");
  const autoReplyAllBtn = $("#autoReplyAll");
  const filterBtns = $$(".filter-btn");

  let commentsData = [];
  let currentFilter = "all";

  // Filter buttons
  filterBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentFilter = btn.dataset.filter;
      renderComments();
    });
  });

  async function loadComments() {
    try {
      commentsData = await api("/api/comments");
      renderComments();
    } catch (e) {
      console.error("댓글 로드 실패:", e);
    }
  }

  function renderComments() {
    // Clear existing items
    commentList.querySelectorAll(".comment-item").forEach((el) => el.remove());

    // Filter
    let filtered = commentsData;
    if (currentFilter === "pending") {
      filtered = commentsData.filter((c) => !c.replied);
    } else if (currentFilter === "replied") {
      filtered = commentsData.filter((c) => c.replied);
    }

    const pendingCount = commentsData.filter((c) => !c.replied).length;
    commentCountBadge.textContent = pendingCount;

    if (filtered.length === 0) {
      commentEmptyState.classList.remove("hidden");
      return;
    }
    commentEmptyState.classList.add("hidden");

    filtered.forEach((comment) => {
      const item = document.createElement("div");
      item.className = "comment-item";
      item.dataset.commentId = comment.id;
      item.dataset.status = comment.replied ? "replied" : "pending";

      // Meta row
      const meta = document.createElement("div");
      meta.className = "comment-meta";

      const username = document.createElement("strong");
      username.className = "comment-username";
      username.textContent = `@${comment.username}`;
      meta.appendChild(username);

      const badge = document.createElement("span");
      badge.className = `comment-status-badge ${comment.replied ? "replied" : "pending"}`;
      badge.textContent = comment.replied ? "완료" : "대기";
      meta.appendChild(badge);

      if (comment.post_url) {
        const link = document.createElement("a");
        link.className = "comment-post-link";
        link.href = comment.post_url;
        link.target = "_blank";
        link.textContent = "게시물";
        meta.appendChild(link);
      }
      item.appendChild(meta);

      // Comment text
      const text = document.createElement("p");
      text.className = "comment-text";
      text.textContent = comment.text;
      item.appendChild(text);

      // Reply preview (if replied)
      if (comment.replied && comment.reply_text) {
        const preview = document.createElement("div");
        preview.className = "comment-reply-preview";
        preview.innerHTML = `<span class="reply-label">답글:</span>${escapeHtml(comment.reply_text)}`;
        item.appendChild(preview);
      }

      // Reply input area (if not replied)
      if (!comment.replied) {
        const replyArea = document.createElement("div");
        replyArea.className = "comment-reply-area";
        replyArea.innerHTML =
          `<input type="text" class="reply-input" placeholder="답글을 입력하세요...">` +
          `<button class="btn-action btn-small reply-send">전송</button>` +
          `<button class="btn-action btn-small reply-ai">🤖 AI</button>`;
        item.appendChild(replyArea);
      }

      commentList.appendChild(item);
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Event delegation for reply buttons
  commentList.addEventListener("click", async (e) => {
    const item = e.target.closest(".comment-item");
    if (!item) return;
    const commentId = item.dataset.commentId;

    if (e.target.classList.contains("reply-send")) {
      const input = item.querySelector(".reply-input");
      const text = input.value.trim();
      if (!text) { alert("답글을 입력해주세요."); return; }
      await replyToComment(commentId, text);
    }

    if (e.target.classList.contains("reply-ai")) {
      if (!confirm("AI가 자동으로 답글을 생성하여 게시합니다.")) return;
      await replyToComment(commentId, "");
    }
  });

  async function replyToComment(commentId, replyText) {
    showLoading(replyText ? "답글 게시 중..." : "AI 답글 생성 중...");
    try {
      const data = await apiPost("/api/comments/reply", {
        comment_id: commentId,
        reply_text: replyText,
      });
      if (data.error) {
        alert(`답글 실패: ${data.error}`);
      } else {
        loadComments();
      }
    } catch (e) {
      alert("답글 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
    }
  }

  // Scan comments
  scanCommentsBtn.addEventListener("click", async () => {
    showLoading("Instagram 댓글 스캔 중...");
    scanCommentsBtn.disabled = true;

    try {
      const data = await apiPost("/api/comments/scan", { max_posts: 5 });
      if (data.error) {
        alert(`스캔 실패: ${data.error}`);
      } else {
        alert(data.message);
        loadComments();
      }
    } catch (e) {
      alert("스캔 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
      scanCommentsBtn.disabled = false;
    }
  });

  // Auto-reply all
  autoReplyAllBtn.addEventListener("click", async () => {
    const pending = commentsData.filter((c) => !c.replied).length;
    if (pending === 0) { alert("답글할 댓글이 없습니다."); return; }
    if (!confirm(`대기 중인 ${pending}개 댓글에 AI 자동 답글을 달까요?`)) return;

    showLoading("자동 답글 중...");
    autoReplyAllBtn.disabled = true;

    try {
      const data = await apiPost("/api/comments/auto-reply", { max_replies: 5 });
      if (data.error) {
        alert(`자동 답글 실패: ${data.error}`);
      } else {
        alert(data.message);
        loadComments();
      }
    } catch (e) {
      alert("자동 답글 중 오류가 발생했습니다.");
    } finally {
      hideLoading();
      autoReplyAllBtn.disabled = false;
    }
  });

  // ── Threads Tab ────────────────────────────────────────

  const threadsText = $("#threadsText");
  const threadsTopic = $("#threadsTopic");
  const generateThreadsBtn = $("#generateThreads");
  const postThreadsBtn = $("#postThreads");
  const threadsHistory = $("#threadsHistory");
  const threadsEmpty = $("#threadsEmpty");

  // Threads image
  const threadsSrcBtns = $$(".threads-src-btn");
  const threadsUploadSection = $("#threadsUploadSection");
  const threadsAiSection = $("#threadsAiSection");
  const threadsPreviewSection = $("#threadsPreviewSection");
  const threadsPreviewImg = $("#threadsPreviewImg");
  const threadsImageFile = $("#threadsImageFile");
  const threadsAiPrompt = $("#threadsAiPrompt");
  const threadsGenerateImageBtn = $("#threadsGenerateImage");
  const threadsRemoveImageBtn = $("#threadsRemoveImage");

  let threadsItems = [];
  let threadsFilename = "";

  // Source toggle
  threadsSrcBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      threadsSrcBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const src = btn.dataset.source;
      threadsUploadSection.classList.toggle("hidden", src !== "upload");
      threadsAiSection.classList.toggle("hidden", src !== "ai");
      if (src === "none") {
        threadsFilename = "";
        threadsPreviewImg.src = "";
        threadsPreviewSection.classList.add("hidden");
      }
    });
  });

  // Upload
  threadsImageFile.addEventListener("change", async () => {
    const file = threadsImageFile.files[0];
    if (!file) return;
    showLoading("이미지 업로드 중...");
    const formData = new FormData();
    formData.append("image", file);
    try {
      const data = await api("/api/upload-image", { method: "POST", body: formData });
      if (data.error) { alert(`업로드 실패: ${data.error}`); }
      else {
        threadsFilename = data.filename;
        threadsPreviewImg.src = data.url;
        threadsPreviewSection.classList.remove("hidden");
      }
    } catch (e) { alert("업로드 오류"); }
    finally { hideLoading(); }
  });

  // Auto prompt from text
  const threadsAutoPromptBtn = $("#threadsAutoPrompt");
  threadsAutoPromptBtn.addEventListener("click", async () => {
    const text = threadsText.value.trim() || threadsTopic.value.trim() || "일상";
    showLoading("프롬프트 생성 중...");
    try {
      const data = await apiPost("/api/generate-image-prompt", {
        caption: text,
        platform: "threads",
      });
      if (data.error) { alert(data.error); }
      else { threadsAiPrompt.value = data.prompt; }
    } catch (e) { alert("프롬프트 생성 오류"); }
    finally { hideLoading(); }
  });

  // AI image
  threadsGenerateImageBtn.addEventListener("click", async () => {
    const topic = threadsAiPrompt.value.trim();
    if (!topic) { alert("이미지 주제를 입력해주세요."); return; }
    showLoading("AI 이미지 생성 중...");
    threadsGenerateImageBtn.disabled = true;
    try {
      const data = await apiPost("/api/generate-image", { topic });
      if (data.error) { alert(`생성 실패: ${data.error}`); }
      else {
        threadsFilename = data.filename;
        threadsPreviewImg.src = data.url;
        threadsPreviewSection.classList.remove("hidden");
      }
    } catch (e) { alert("이미지 생성 오류"); }
    finally { hideLoading(); threadsGenerateImageBtn.disabled = false; }
  });

  // Remove image
  threadsRemoveImageBtn.addEventListener("click", () => {
    threadsFilename = "";
    threadsPreviewImg.src = "";
    threadsPreviewSection.classList.add("hidden");
    threadsImageFile.value = "";
  });

  // Generate text
  generateThreadsBtn.addEventListener("click", async () => {
    const topic = threadsTopic.value.trim() || "일상";
    showLoading("Threads 글 생성 중...");
    generateThreadsBtn.disabled = true;
    try {
      const data = await apiPost("/api/generate-threads", { topic });
      if (data.error) { alert(`생성 실패: ${data.error}`); }
      else { threadsText.value = data.text; }
    } catch (e) { alert("생성 중 오류가 발생했습니다."); }
    finally { hideLoading(); generateThreadsBtn.disabled = false; }
  });

  // Post
  postThreadsBtn.addEventListener("click", () => {
    const text = threadsText.value.trim();
    if (!text) { alert("게시할 글을 입력하거나 AI로 생성해주세요."); return; }

    threadsItems.unshift({
      text,
      image: threadsFilename ? `/uploads/${threadsFilename}` : "",
      topic: threadsTopic.value.trim() || "",
      time: new Date().toISOString(),
    });
    renderThreadsHistory();

    threadsText.value = "";
    threadsTopic.value = "";
    threadsFilename = "";
    threadsPreviewImg.src = "";
    threadsPreviewSection.classList.add("hidden");
    threadsImageFile.value = "";

    alert("Threads 게시글이 저장되었습니다!");
  });

  function renderThreadsHistory() {
    threadsHistory.querySelectorAll(".threads-history-item").forEach((el) => el.remove());

    if (threadsItems.length === 0) { threadsEmpty.classList.remove("hidden"); return; }
    threadsEmpty.classList.add("hidden");

    threadsItems.forEach((item) => {
      const div = document.createElement("div");
      div.className = "threads-history-item";

      if (item.image) {
        const img = document.createElement("img");
        img.src = item.image;
        img.alt = "";
        img.style.cssText = "width:100%;max-height:200px;object-fit:cover;border-radius:8px;margin-bottom:8px;";
        div.appendChild(img);
      }

      const p = document.createElement("p");
      p.textContent = item.text;
      div.appendChild(p);

      const meta = document.createElement("div");
      meta.className = "threads-item-meta";
      meta.textContent = `${item.topic ? item.topic + " · " : ""}${formatDate(item.time)}`;
      div.appendChild(meta);

      threadsHistory.appendChild(div);
    });
  }

  // ── Monitor Tab ────────────────────────────────────────

  const monitorFeed = $("#monitorFeed");
  const monitorEmpty = $("#monitorEmpty");
  const monStatusDot = $("#monitorStatusDot");
  const monStatusText = $("#monitorStatusText");
  const monCycleInfo = $("#monitorCycleInfo");
  const monHashtagCloud = $("#monHashtagCloud");
  const monSearchCloud = $("#monSearchCloud");
  const monPostCount = $("#monPostCount");

  let lastMonitorData = null;
  let monitorInterval = null;

  async function loadMonitorStatus() {
    try {
      const data = await api("/api/monitor/status");
      lastMonitorData = data;

      // Stats
      $("#monStatCycle").textContent = data.cycle_count;
      $("#monStatSamples").textContent = data.total_samples;
      $("#monStatHashtags").textContent = data.discovered_hashtags.length;
      $("#monStatSearches").textContent = data.discovered_searches.length;

      // Status indicator
      const history = data.history || [];
      const lastCycle = history[history.length - 1];
      if (lastCycle) {
        const lastDate = new Date(lastCycle.date);
        const ago = Math.floor((Date.now() - lastDate.getTime()) / 60000);
        if (ago < 10) {
          monStatusDot.className = "monitor-status-indicator running";
          monStatusText.textContent = "학습 진행 중";
        } else {
          monStatusDot.className = "monitor-status-indicator idle";
          monStatusText.textContent = "대기 중";
        }
        monCycleInfo.textContent = `마지막 사이클: ${ago < 60 ? ago + "분 전" : Math.floor(ago/60) + "시간 전"}`;
      }

      // Hashtag cloud
      monHashtagCloud.innerHTML = "";
      const baseHashtags = [
        "일상스타그램", "카페스타그램", "데일리룩", "서울카페",
        "오오티디", "감성스타그램", "맛집스타그램", "패션스타그램",
      ];
      const allHashtags = [...new Set([...baseHashtags, ...data.discovered_hashtags])];
      allHashtags.forEach((tag) => {
        const chip = document.createElement("span");
        chip.className = "tag-chip";
        chip.textContent = `#${tag}`;
        monHashtagCloud.appendChild(chip);
      });

      // Search cloud
      monSearchCloud.innerHTML = "";
      const baseSearches = ["일상 브이로그", "서울 카페 추천", "봄 데일리룩"];
      const allSearches = [...new Set([...baseSearches, ...data.discovered_searches])];
      allSearches.forEach((s) => {
        const chip = document.createElement("span");
        chip.className = "tag-chip search";
        chip.textContent = s;
        monSearchCloud.appendChild(chip);
      });
    } catch (e) {
      console.error("모니터 상태 로드 실패:", e);
    }
  }

  async function loadMonitorPosts() {
    try {
      const posts = await api("/api/monitor/posts?limit=100");
      monPostCount.textContent = posts.length;

      // Clear existing
      monitorFeed.querySelectorAll(".monitor-post-item").forEach((el) => el.remove());

      if (posts.length === 0) {
        monitorEmpty.classList.remove("hidden");
        return;
      }
      monitorEmpty.classList.add("hidden");

      posts.forEach((post) => {
        const item = document.createElement("div");
        item.className = "monitor-post-item";

        // Source label: extract readable name from filename
        let sourceLabel = post.source;
        const m = sourceLabel.match(/^(hashtag|search|user|explore)_(.+?)_\d/);
        if (m) sourceLabel = (m[1] === "hashtag" ? "#" : "") + m[2];

        const meta = document.createElement("div");
        meta.className = "monitor-post-meta";
        meta.innerHTML =
          `<span class="monitor-post-user">@${escapeHtml(post.user)}</span>` +
          `<span class="monitor-post-source">${escapeHtml(sourceLabel)}</span>` +
          (post.likes ? `<span class="monitor-post-likes">♥ ${post.likes}</span>` : "");
        item.appendChild(meta);

        const caption = document.createElement("p");
        caption.className = "monitor-post-caption";
        caption.textContent = post.caption;
        item.appendChild(caption);

        if (post.hashtags && post.hashtags.length > 0) {
          const tags = document.createElement("div");
          tags.className = "monitor-post-tags";
          tags.textContent = post.hashtags.map((t) => `#${t}`).join(" ");
          item.appendChild(tags);
        }

        monitorFeed.appendChild(item);
      });
    } catch (e) {
      console.error("모니터 게시글 로드 실패:", e);
    }
  }

  // Start/stop polling when monitor tab is active
  function startMonitorPolling() {
    loadMonitorStatus();
    loadMonitorPosts();
    if (!monitorInterval) {
      monitorInterval = setInterval(() => {
        loadMonitorStatus();
        loadMonitorPosts();
      }, 5000);
    }
  }

  function stopMonitorPolling() {
    if (monitorInterval) {
      clearInterval(monitorInterval);
      monitorInterval = null;
    }
  }

  // Hook into tab switching
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.dataset.tab === "monitor") {
        startMonitorPolling();
      } else {
        stopMonitorPolling();
      }
    });
  });

  // ── Init ───────────────────────────────────────────────

  loadPosts();
  loadComments();
})();
