from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk
import pytesseract

from src.invoice_parser import InvoiceItem, parse_invoice_text


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PHOTO_SUFFIX_LABELS = ("0 основное", "1 линейка", "2 проба", "3 доп.")
PHOTO_SUFFIX_COLORS = ("#34d399", "#f43f5e", "#f59e0b", "#8b5cf6")


class InvoiceRenamerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Накладная OCR + переименование фото")
        self.root.geometry("1320x780")
        self.root.minsize(1100, 680)

        self.items: list[InvoiceItem] = []
        self.photo_paths: list[Path] = []
        self.photo_cards: dict[Path, tk.Frame] = {}
        self.photo_suffixes: dict[Path, int] = {}
        self.thumbnail_refs: list[ImageTk.PhotoImage] = []
        self.preview_refs: list[ImageTk.PhotoImage] = []
        self.photo_grid_columns = 0
        self.invoice_preview_source: Image.Image | None = None
        self.invoice_preview_ref: ImageTk.PhotoImage | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.root.configure(bg="#111827")

        main = tk.Frame(self.root, bg="#111827")
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = tk.Frame(main, bg="#172033", padx=12, pady=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(4, weight=1)

        right = tk.Frame(main, bg="#172033", padx=12, pady=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        self._build_invoice_panel(left)
        self._build_photo_panel(right)

    def _build_invoice_panel(self, parent: tk.Frame) -> None:
        title = tk.Label(parent, text="Накладная", bg="#172033", fg="#f43f5e", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")

        buttons = tk.Frame(parent, bg="#172033")
        buttons.grid(row=1, column=0, sticky="ew", pady=8)
        buttons.columnconfigure((0, 1), weight=1)

        tk.Button(buttons, text="Выбрать фото/PDF накладной", command=self.load_invoice, bg="#34d399", fg="#07111f").grid(
            row=0, column=0, sticky="ew", padx=(0, 5)
        )
        tk.Button(buttons, text="Вставить OCR-текст вручную", command=self.open_text_paste, bg="#60a5fa", fg="#07111f").grid(
            row=0, column=1, sticky="ew", padx=(5, 0)
        )

        self.status_label = tk.Label(parent, text="Загрузите накладную. Нужные поля: код, 201000…, вес, сумма.", bg="#172033", fg="#9ca3af")
        self.status_label.grid(row=2, column=0, sticky="w", pady=(0, 8))

        preview_panel = tk.Frame(parent, bg="#0f172a", padx=8, pady=8)
        preview_panel.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        preview_panel.columnconfigure(0, weight=1)

        tk.Label(preview_panel, text="Превью накладной", bg="#0f172a", fg="#9ca3af", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.invoice_preview_canvas = tk.Canvas(
            preview_panel,
            bg="#111827",
            height=240,
            highlightthickness=0,
        )
        self.invoice_preview_canvas.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.invoice_preview_canvas.create_text(
            12,
            120,
            anchor="w",
            fill="#6b7280",
            text="После выбора файла здесь будет сама накладная",
        )
        self.invoice_preview_canvas.bind("<Configure>", lambda _event: self.update_invoice_preview())
        self.invoice_preview_canvas.bind("<Button-1>", lambda _event: self.show_invoice_large_preview())

        columns = ("short_code", "long_id", "weight", "total")
        self.tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse")
        headings = {
            "short_code": "Код",
            "long_id": "201000…",
            "weight": "Вес",
            "total": "Сумма",
        }
        widths = {"short_code": 90, "long_id": 170, "weight": 80, "total": 110}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor=tk.CENTER)
        self.tree.grid(row=4, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self.on_invoice_select)

        actions = tk.Frame(parent, bg="#172033")
        actions.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure((0, 1), weight=1)
        tk.Button(actions, text="Скопировать 201000…", command=self.copy_selected_id, bg="#f43f5e", fg="white").grid(
            row=0, column=0, sticky="ew", padx=(0, 5)
        )
        tk.Button(actions, text="Копировать строку: код / ID / вес / сумма", command=self.copy_selected_row, bg="#374151", fg="white").grid(
            row=0, column=1, sticky="ew", padx=(5, 0)
        )

    def _build_photo_panel(self, parent: tk.Frame) -> None:
        title = tk.Label(parent, text="Фото изделий", bg="#172033", fg="#f43f5e", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")

        buttons = tk.Frame(parent, bg="#172033")
        buttons.grid(row=1, column=0, sticky="ew", pady=8)
        buttons.columnconfigure((0, 1), weight=1)
        tk.Button(buttons, text="Открыть папку с фото", command=self.load_photo_folder, bg="#34d399", fg="#07111f").grid(
            row=0, column=0, sticky="ew", padx=(0, 5)
        )
        tk.Button(buttons, text="Сбросить выбор", command=self.clear_photo_selection, bg="#374151", fg="white").grid(
            row=0, column=1, sticky="ew", padx=(5, 0)
        )

        scroller = tk.Frame(parent, bg="#172033")
        scroller.grid(row=2, column=0, sticky="nsew")
        scroller.rowconfigure(0, weight=1)
        scroller.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(scroller, bg="#0f172a", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(scroller, orient=tk.VERTICAL, command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.photos_frame = tk.Frame(self.canvas, bg="#0f172a")
        self.canvas_window = self.canvas.create_window((0, 0), window=self.photos_frame, anchor="nw")
        self.photos_frame.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.on_photo_canvas_resize)

        rename_panel = tk.Frame(parent, bg="#0f172a", padx=10, pady=10)
        rename_panel.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        rename_panel.columnconfigure(0, weight=1)

        self.photo_status = tk.Label(rename_panel, text="Файлов: 0 | выбрано: 0", bg="#0f172a", fg="#9ca3af")
        self.photo_status.grid(row=0, column=0, sticky="w")

        self.id_entry = tk.Entry(rename_panel, font=("Consolas", 14), bg="#111827", fg="#34d399", insertbackground="#34d399")
        self.id_entry.grid(row=1, column=0, sticky="ew", pady=8)

        tk.Button(rename_panel, text="Переименовать выбранные 1–4 фото", command=self.rename_selected, bg="#34d399", fg="#07111f").grid(
            row=2, column=0, sticky="ew"
        )

    def load_invoice(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Изображения", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff")])
        if not path:
            return

        self.status_label.config(text="Распознаю накладную…")
        self.show_invoice_preview(Path(path))
        threading.Thread(target=self._run_ocr, args=(Path(path),), daemon=True).start()

    def show_invoice_preview(self, path: Path) -> None:
        try:
            image = Image.open(path)
            self.invoice_preview_source = ImageOps.exif_transpose(image).copy()
            self.update_invoice_preview()
        except OSError:
            self.invoice_preview_source = None
            self.invoice_preview_ref = None
            self.invoice_preview_canvas.delete("all")
            self.invoice_preview_canvas.create_text(12, 120, anchor="w", fill="#f43f5e", text="Не удалось открыть превью накладной")

    def update_invoice_preview(self) -> None:
        if self.invoice_preview_source is None:
            return

        width = max(self.invoice_preview_canvas.winfo_width() - 16, 240)
        height = 230
        image = self.invoice_preview_source.copy()
        image.thumbnail((width, height), Image.LANCZOS)
        self.invoice_preview_ref = ImageTk.PhotoImage(image)
        self.invoice_preview_canvas.delete("all")
        x = max((self.invoice_preview_canvas.winfo_width() - image.width) // 2, 0)
        y = max((240 - image.height) // 2, 0)
        self.invoice_preview_canvas.create_image(x, y, anchor="nw", image=self.invoice_preview_ref)
        self.invoice_preview_canvas.create_text(10, 225, anchor="w", fill="#9ca3af", text="Клик — открыть крупно")

    def show_invoice_large_preview(self) -> None:
        if self.invoice_preview_source is None:
            return

        window = tk.Toplevel(self.root)
        window.title("Превью накладной")
        window.geometry("1100x780")
        window.configure(bg="#111827")

        image = self.invoice_preview_source.copy()
        image.thumbnail((1060, 700), Image.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self.preview_refs.append(photo)

        image_label = tk.Label(window, image=photo, bg="#111827")
        image_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Button(window, text="Закрыть", command=window.destroy, bg="#374151", fg="#ffffff").pack(fill=tk.X, padx=10, pady=(0, 10))

    def _run_ocr(self, path: Path) -> None:
        try:
            configure_tesseract()
            text = run_tesseract_ocr(path)
            items = parse_invoice_text(text)
            self.root.after(0, lambda: self.show_items(items, f"Найдено строк: {len(items)}"))
        except Exception as error:
            error_message = build_ocr_error_message(error)
            self.root.after(0, lambda: self.status_label.config(text="Ошибка OCR"))
            self.root.after(0, lambda: messagebox.showerror("OCR не сработал", error_message))

    def open_text_paste(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Вставить текст накладной")
        window.geometry("820x520")
        window.configure(bg="#111827")

        text_widget = tk.Text(window, wrap=tk.WORD, bg="#0f172a", fg="#e5e7eb", insertbackground="#e5e7eb")
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        def parse_pasted_text() -> None:
            items = parse_invoice_text(text_widget.get("1.0", tk.END))
            self.show_items(items, f"Найдено строк из вставленного текста: {len(items)}")
            window.destroy()

        tk.Button(window, text="Разобрать текст", command=parse_pasted_text, bg="#34d399", fg="#07111f").pack(fill=tk.X, padx=10, pady=(0, 10))

    def show_items(self, items: list[InvoiceItem], status: str) -> None:
        self.items = items
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(items):
            self.tree.insert("", tk.END, iid=str(index), values=(item.short_code, item.long_id, item.weight, item.total))
        self.status_label.config(text=status)
        if not items:
            messagebox.showwarning("Не найдено", "Не нашёл строки вида: ЦА604 (2010001488255). Попробуйте вставить OCR-текст вручную.")

    def on_invoice_select(self, _event: tk.Event) -> None:
        selected = self._selected_item()
        if selected is None:
            return
        self.id_entry.delete(0, tk.END)
        self.id_entry.insert(0, selected.long_id)
        self._copy_to_clipboard(selected.long_id)

    def copy_selected_id(self) -> None:
        selected = self._selected_item()
        if selected is None:
            messagebox.showinfo("Выберите строку", "Сначала выберите строку с нужным кодом.")
            return
        self._copy_to_clipboard(selected.long_id)

    def copy_selected_row(self) -> None:
        selected = self._selected_item()
        if selected is None:
            messagebox.showinfo("Выберите строку", "Сначала выберите строку с нужным кодом.")
            return
        self._copy_to_clipboard(f"{selected.short_code}\t{selected.long_id}\t{selected.weight}\t{selected.total}")

    def _selected_item(self) -> InvoiceItem | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.items[int(selection[0])]

    def _copy_to_clipboard(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)

    def load_photo_folder(self) -> None:
        folder = filedialog.askdirectory()
        if not folder:
            return

        self.photo_paths = sorted(path for path in Path(folder).iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file())
        self.photo_suffixes = {}
        self._render_photo_grid()

    def _render_photo_grid(self) -> None:
        for widget in self.photos_frame.winfo_children():
            widget.destroy()
        self.photo_cards.clear()
        self.thumbnail_refs.clear()

        columns = self._calculate_photo_columns()
        self.photo_grid_columns = columns
        for column in range(columns):
            self.photos_frame.columnconfigure(column, weight=1)

        for index, path in enumerate(self.photo_paths):
            card = tk.Frame(self.photos_frame, bg="#1f2937", bd=2, relief=tk.FLAT)
            card.grid(row=index // columns, column=index % columns, padx=6, pady=6, sticky="nsew")
            self.photo_cards[path] = card

            try:
                image = Image.open(path)
                image = ImageOps.exif_transpose(image)
                image.thumbnail((150, 150), Image.LANCZOS)
                thumbnail = ImageTk.PhotoImage(image)
                self.thumbnail_refs.append(thumbnail)
                image_label = tk.Label(card, image=thumbnail, bg="#1f2937", cursor="hand2")
            except Exception:
                image_label = tk.Label(card, text="нет превью", bg="#1f2937", fg="#9ca3af", width=18, height=8)

            image_label.pack(padx=4, pady=(4, 2))
            image_label.bind("<Button-1>", lambda _event, photo_path=path: self.show_photo_preview(photo_path))

            name = tk.Label(card, text=path.name, bg="#1f2937", fg="#d1d5db", wraplength=150, font=("Segoe UI", 8))
            name.pack(fill=tk.X, padx=4, pady=(0, 4))
            name.bind("<Button-1>", lambda _event, photo_path=path: self.show_photo_preview(photo_path))

            order_label = tk.Label(card, text="не выбрано", bg="#111827", fg="#9ca3af", font=("Segoe UI", 9, "bold"))
            order_label.pack(fill=tk.X, padx=4, pady=(0, 4))
            card.order_label = order_label

            suffix_buttons = tk.Frame(card, bg="#1f2937")
            suffix_buttons.pack(fill=tk.X, padx=4, pady=(0, 4))
            card.suffix_buttons = suffix_buttons
            for suffix_index, color in enumerate(PHOTO_SUFFIX_COLORS):
                button = tk.Button(
                    suffix_buttons,
                    text=str(suffix_index),
                    bg="#111827",
                    fg=color,
                    activebackground=color,
                    activeforeground="#ffffff",
                    relief=tk.FLAT,
                    command=lambda photo_path=path, suffix=suffix_index: self.assign_photo_suffix(photo_path, suffix),
                )
                button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0 if suffix_index == 0 else 2, 0))
            clear_button = tk.Button(
                suffix_buttons,
                text="×",
                bg="#374151",
                fg="#e5e7eb",
                relief=tk.FLAT,
                command=lambda photo_path=path: self.clear_photo_suffix(photo_path),
            )
            clear_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self._paint_photo_cards()
        self._update_photo_status()

    def _calculate_photo_columns(self) -> int:
        width = max(self.canvas.winfo_width(), self.canvas.winfo_reqwidth(), 1)
        return max(1, width // 170)

    def on_photo_canvas_resize(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        columns = max(1, event.width // 170)
        if self.photo_paths and columns != self.photo_grid_columns:
            self._render_photo_grid()

    def assign_photo_suffix(self, path: Path, suffix_index: int) -> None:
        for selected_path, selected_suffix in list(self.photo_suffixes.items()):
            if selected_path != path and selected_suffix == suffix_index:
                del self.photo_suffixes[selected_path]
        self.photo_suffixes[path] = suffix_index
        self._paint_photo_cards()
        self._update_photo_status()

    def clear_photo_suffix(self, path: Path) -> None:
        self.photo_suffixes.pop(path, None)
        self._paint_photo_cards()
        self._update_photo_status()

    def show_photo_preview(self, path: Path) -> None:
        window = tk.Toplevel(self.root)
        window.title(path.name)
        window.geometry("900x720")
        window.configure(bg="#111827")

        try:
            image = Image.open(path)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((860, 560), Image.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.preview_refs.append(photo)
            image_label = tk.Label(window, image=photo, bg="#111827")
            image_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        except OSError as error:
            tk.Label(window, text=str(error), bg="#111827", fg="#f43f5e").pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        buttons = tk.Frame(window, bg="#111827")
        buttons.pack(fill=tk.X, padx=10, pady=(0, 10))
        for suffix_index, label in enumerate(PHOTO_SUFFIX_LABELS):
            tk.Button(
                buttons,
                text=label,
                bg=PHOTO_SUFFIX_COLORS[suffix_index],
                fg="#ffffff" if suffix_index else "#07111f",
                command=lambda suffix=suffix_index: (self.assign_photo_suffix(path, suffix), window.destroy()),
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0 if suffix_index == 0 else 6, 0))
        tk.Button(buttons, text="снять выбор", bg="#374151", fg="#ffffff", command=lambda: (self.clear_photo_suffix(path), window.destroy())).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
        )

    def clear_photo_selection(self) -> None:
        self.photo_suffixes = {}
        self._paint_photo_cards()
        self._update_photo_status()

    def _paint_photo_cards(self) -> None:
        for path, card in self.photo_cards.items():
            selected_index = self.photo_suffixes.get(path)
            is_selected = selected_index is not None
            bg = PHOTO_SUFFIX_COLORS[selected_index] if selected_index is not None else "#1f2937"
            fg = "#07111f" if is_selected else "#d1d5db"
            badge = PHOTO_SUFFIX_LABELS[selected_index] if selected_index is not None else "не выбрано"
            card.config(bg=bg)
            for child in card.winfo_children():
                if child is getattr(card, "order_label", None):
                    child.config(text=badge, bg=bg if is_selected else "#111827", fg="#ffffff" if is_selected else "#9ca3af")
                elif child is getattr(card, "suffix_buttons", None):
                    child.config(bg=bg)
                    for button_index, button in enumerate(child.winfo_children()):
                        active = button_index == selected_index
                        if active and button_index < len(PHOTO_SUFFIX_COLORS):
                            button.config(bg=PHOTO_SUFFIX_COLORS[button_index], fg="#ffffff" if button_index else "#07111f")
                        elif button_index < len(PHOTO_SUFFIX_COLORS):
                            button.config(bg="#111827", fg=PHOTO_SUFFIX_COLORS[button_index])
                        else:
                            button.config(bg="#374151", fg="#e5e7eb")
                else:
                    child.config(bg=bg, fg=fg if isinstance(child, tk.Label) else child.cget("fg"))

    def _update_photo_status(self) -> None:
        selected = sorted(self.photo_suffixes.items(), key=lambda entry: entry[1])
        order = " → ".join(PHOTO_SUFFIX_LABELS[suffix] for _path, suffix in selected)
        suffix_text = f" | выбраны: {order}" if order else ""
        self.photo_status.config(text=f"Файлов: {len(self.photo_paths)} | выбрано: {len(self.photo_suffixes)}{suffix_text}")

    def rename_selected(self) -> None:
        code = self.id_entry.get().strip()
        if not code:
            messagebox.showwarning("Нет ID", "Выберите строку накладной или вставьте ID 201000… вручную.")
            return
        if not self.photo_suffixes:
            messagebox.showwarning("Нет фото", "Выберите от 1 до 4 фотографий.")
            return

        if not code.startswith("201000") or not code.isdigit():
            if not messagebox.askyesno("Проверить ID", f"ID выглядит необычно: {code}\nВсё равно переименовать?"):
                return

        selected = sorted(self.photo_suffixes.items(), key=lambda entry: entry[1])
        preview = "\n".join(f"{path.name} → {self._new_photo_path(path, code, suffix).name}" for path, suffix in selected)
        if not messagebox.askyesno("Подтвердить", f"Переименовать файлы?\n\n{preview}"):
            return

        try:
            renamed_paths: list[Path] = []
            for old_path, suffix in selected:
                new_path = self._new_photo_path(old_path, code, suffix)
                old_path.rename(new_path)
                renamed_paths.append(new_path)
                photo_index = self.photo_paths.index(old_path)
                self.photo_paths[photo_index] = new_path

            self.photo_suffixes = {}
            self._render_photo_grid()
            messagebox.showinfo("Готово", f"Переименовано файлов: {len(renamed_paths)}")
        except OSError as error:
            messagebox.showerror("Ошибка переименования", str(error))

    def _new_photo_path(self, old_path: Path, code: str, index: int) -> Path:
        suffix = "" if index == 0 else f"_{index}"
        candidate = old_path.with_name(f"{code}{suffix}{old_path.suffix.lower()}")
        if candidate.exists() and candidate != old_path:
            raise FileExistsError(f"Файл уже существует: {candidate}")
        return candidate


def main() -> None:
    configure_tesseract()

    root = tk.Tk()
    app = InvoiceRenamerApp(root)
    root.mainloop()


def configure_tesseract() -> None:
    candidates = [
        os.environ.get("TESSERACT_PATH"),
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


def run_tesseract_ocr(path: Path) -> str:
    command = [
        pytesseract.pytesseract.tesseract_cmd,
        str(path),
        "stdout",
        "-l",
        "rus+eng",
        "--psm",
        "6",
    ]
    completed = subprocess.run(command, capture_output=True, check=True)
    return completed.stdout.decode("utf-8", errors="replace")


def build_ocr_error_message(error: Exception) -> str:
    configured = pytesseract.pytesseract.tesseract_cmd
    message = str(error)
    return (
        f"{message}\n\n"
        f"Путь, который пробует приложение: {configured}\n\n"
        "Что проверить:\n"
        "1. Есть ли файл C:\\Program Files\\Tesseract-OCR\\tesseract.exe\n"
        "2. Установлен ли русский язык: tesseract --list-langs\n"
        "3. Если путь другой, запустите так:\n"
        "   set TESSERACT_PATH=ваш\\путь\\tesseract.exe\n"
        "   invoice-renamer.bat"
    )


if __name__ == "__main__":
    main()
