"use client";

import { useEffect } from "react";

export function CodeCopyButtons() {
  useEffect(() => {
    const pres = document.querySelectorAll(".prose-docs pre");

    pres.forEach((pre) => {
      if (pre.querySelector(".copy-btn")) return;

      const wrapper = document.createElement("div");
      wrapper.className = "relative group";
      pre.parentNode?.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);

      const btn = document.createElement("button");
      btn.className =
        "copy-btn absolute top-3 right-3 p-1.5 rounded-md bg-zinc-800/80 border border-white/10 text-zinc-400 opacity-0 group-hover:opacity-100 hover:text-zinc-100 hover:bg-zinc-700 transition-all duration-200 cursor-pointer";
      btn.setAttribute("aria-label", "Copy to clipboard");
      btn.innerHTML = `<svg class="w-4 h-4 copy-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg><svg class="w-4 h-4 check-icon hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`;

      btn.addEventListener("click", () => {
        const code = pre.querySelector("code");
        const text = code?.textContent || pre.textContent || "";
        navigator.clipboard.writeText(text).then(() => {
          const copyIcon = btn.querySelector(".copy-icon") as HTMLElement;
          const checkIcon = btn.querySelector(".check-icon") as HTMLElement;
          copyIcon.classList.add("hidden");
          checkIcon.classList.remove("hidden");
          checkIcon.style.color = "#34d399"; // emerald-400
          setTimeout(() => {
            copyIcon.classList.remove("hidden");
            checkIcon.classList.add("hidden");
          }, 2000);
        });
      });

      wrapper.appendChild(btn);
    });
  }, []);

  return null;
}
