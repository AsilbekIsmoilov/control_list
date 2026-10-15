let currentIndex = -1;

function filterDropdown() {
    const input = document.getElementById("operator-name");
    const filter = input.value.trim().toLowerCase();
    const dropdown = document.getElementById("dropdown");
    const items = dropdown.getElementsByClassName("dropdown-item");

    if (!filter) {
        dropdown.style.display = "none";
        currentIndex = -1;
        document
          .querySelector(".dashboard.list2-page")
          .classList.remove("dropdown-open");
        return;
    }

    let anyVisible = false;
    currentIndex = -1;

    for (let item of items) {
        const fullName = item.dataset.name.toLowerCase();
        const numberMatch = fullName.match(/\((\d+)\)/);
        const operatorNumber = numberMatch ? numberMatch[1] : "";

        if (fullName.includes(filter) || operatorNumber === filter) {
            item.style.display = "block";
            anyVisible = true;
        } else {
            item.style.display = "none";
        }

        item.classList.remove("active");
    }

    dropdown.style.display = anyVisible ? "block" : "none";

    document
      .querySelector(".dashboard.list2-page")
      .classList.toggle("dropdown-open", anyVisible);
}

function highlightItem(items) {
    items.forEach((item, index) => {
        item.classList.toggle("active", index === currentIndex);
        if (index === currentIndex) {
            item.scrollIntoView({ block: "nearest" });
        }
    });
}

function handleKeyDown(event) {
    const input = document.getElementById("operator-name");
    const dropdown = document.getElementById("dropdown");

    const items = Array.from(
        dropdown.getElementsByClassName("dropdown-item")
    ).filter(item => item.style.display !== "none");

    if (!items.length) return;

    if (event.key === "ArrowDown") {
        event.preventDefault();
        if (currentIndex < items.length - 1) {
            currentIndex++;
            highlightItem(items);
        }
    }

    if (event.key === "ArrowUp") {
        event.preventDefault();
        if (currentIndex > 0) {
            currentIndex--;
            highlightItem(items);
        }
    }

    if (event.key === "Enter") {
        event.preventDefault();
        if (!input.value.trim()) return;

        const selected =
            currentIndex === -1 ? items[0] : items[currentIndex];

        if (selected) {
            input.value = selected.dataset.name;
            dropdown.style.display = "none";
            currentIndex = -1;
            document
              .querySelector(".dashboard.list2-page")
              .classList.remove("dropdown-open");
            document.getElementById("operator-form").submit();
        }
    }
}

// === Events ===
const input = document.getElementById("operator-name");

input.addEventListener("input", filterDropdown);
input.addEventListener("keydown", handleKeyDown);

document.querySelectorAll("#dropdown .dropdown-item").forEach(item => {
    item.addEventListener("click", () => {
        input.value = item.dataset.name;
        document.getElementById("dropdown").style.display = "none";
        currentIndex = -1;
        document
          .querySelector(".dashboard.list2-page")
          .classList.remove("dropdown-open");
        document.getElementById("operator-form").submit();
    });
});

document.addEventListener("click", e => {
    if (!e.target.closest(".input-wrapper")) {
        document.getElementById("dropdown").style.display = "none";
        currentIndex = -1;
        document
          .querySelector(".dashboard.list2-page")
          .classList.remove("dropdown-open");
    }
});