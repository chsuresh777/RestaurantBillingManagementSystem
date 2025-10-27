"""
Restaurant Billing & Management System
- Single-file Tkinter GUI
- OOP: Customer, Item, Bill
- SQLite persistence (bills table)
- Search previous bills by bill number
- Export invoice to PDF (uses fpdf2 if available) or text fallback
- Input validation and error handling

Save as: restaurant_billing_upgraded.py
Run: python restaurant_billing_upgraded.py
"""

import json
import random
import sqlite3
from datetime import datetime
from tkinter import *
from tkinter import messagebox, ttk, filedialog

# Try to import PDF library (optional). If not available, we'll fall back to text invoice.
try:
    from fpdf import FPDF  # fpdf2
    FPDF_AVAILABLE = True
except Exception:
    FPDF_AVAILABLE = False


# ----------------------------
# Data & Database Layer
# ----------------------------
class Item:
    def __init__(self, code: str, name: str, unit_price: float, qty: int = 0):
        self.code = code
        self.name = name
        self.unit_price = float(unit_price)
        self.qty = int(qty)

    @property
    def amount(self) -> float:
        return round(self.unit_price * self.qty, 2)

    def to_dict(self):
        return {"code": self.code, "name": self.name, "unit_price": self.unit_price, "qty": self.qty, "amount": self.amount}


class Customer:
    def __init__(self, name: str, phone: str):
        self.name = name.strip()
        self.phone = phone.strip()


class Bill:
    TAX_RATES = {
        "snacks": 0.05,      # 5%
        "grocery": 0.01,     # 1%
        "hygiene": 0.10      # 10%
    }

    def __init__(self, bill_no: str, customer: Customer, date: str = None):
        self.bill_no = bill_no
        self.customer = customer
        self.items = []  # list of (category, Item)
        self.date = date if date else datetime.now().isoformat(timespec='seconds')

    def add_item(self, category: str, item: Item):
        # if qty is 0, ignore
        if item.qty > 0:
            self.items.append((category, item))

    def totals_by_category(self):
        cat_totals = {}
        for cat, item in self.items:
            cat_totals.setdefault(cat, 0.0)
            cat_totals[cat] += item.amount
        # round totals
        return {k: round(v, 2) for k, v in cat_totals.items()}

    def taxes_by_category(self):
        totals = self.totals_by_category()
        taxes = {}
        for cat, amt in totals.items():
            rate = self.TAX_RATES.get(cat, 0.0)
            taxes[cat] = round(amt * rate, 2)
        return taxes

    @property
    def subtotal(self):
        return round(sum(item.amount for _, item in self.items), 2)

    @property
    def total_tax(self):
        return round(sum(self.taxes_by_category().values()), 2)

    @property
    def grand_total(self):
        return round(self.subtotal + self.total_tax, 2)

    def to_record(self):
        # For DB: serialize items as JSON list of dicts
        serialized_items = []
        for cat, item in self.items:
            d = item.to_dict()
            d["category"] = cat
            serialized_items.append(d)
        return {
            "bill_no": self.bill_no,
            "customer_name": self.customer.name,
            "phone": self.customer.phone,
            "date": self.date,
            "items": json.dumps(serialized_items),
            "subtotal": self.subtotal,
            "tax": self.total_tax,
            "total": self.grand_total
        }

    @staticmethod
    def from_record(record):
        # record is a dict from DB
        customer = Customer(record["customer_name"], record["phone"])
        bill = Bill(record["bill_no"], customer, date=record["date"])
        items = json.loads(record["items"])
        for itm in items:
            item = Item(itm.get("code", ""), itm["name"], itm["unit_price"], itm["qty"])
            bill.add_item(itm.get("category", "other"), item)
        return bill


class DatabaseManager:
    def __init__(self, db_path="bills.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_no TEXT UNIQUE,
                customer_name TEXT,
                phone TEXT,
                date TEXT,
                items TEXT, -- json
                subtotal REAL,
                tax REAL,
                total REAL
            );
            """
        )
        self.conn.commit()

    def save_bill(self, bill: Bill):
        record = bill.to_record()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO bills (bill_no, customer_name, phone, date, items, subtotal, tax, total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (record["bill_no"], record["customer_name"], record["phone"], record["date"], record["items"],
             record["subtotal"], record["tax"], record["total"])
        )
        self.conn.commit()

    def get_bill(self, bill_no: str):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM bills WHERE bill_no = ?", (bill_no,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return None

    def list_bills(self, limit=50):
        cur = self.conn.cursor()
        cur.execute("SELECT bill_no, customer_name, date, total FROM bills ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        self.conn.close()


# ----------------------------
# GUI Layer (Tkinter)
# ----------------------------
class BillApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Restaurant Billing System — Upgraded")
        self.root.geometry("1200x700")
        self.db = DatabaseManager()

        # --- Data: menu items (code, name, price, category)
        # Map codes to (name, price, category). Customize as needed.
        self.catalog = {
            "S01": ("Samosa", 20.0, "snacks"),
            "S02": ("Paneer Tikka", 150.0, "snacks"),
            "S03": ("Chicken Tikka", 180.0, "snacks"),
            "S04": ("Vegetable Pakora", 60.0, "snacks"),
            "M01": ("Butter Chicken", 220.0, "grocery"),
            "M02": ("Pasta", 120.0, "grocery"),
            "M03": ("Basmati Rice (1kg)", 160.0, "grocery"),
            "M04": ("Paneer Masala", 180.0, "grocery"),
            "H01": ("Noodles", 80.0, "hygiene"),  # note: category names kept per tax mapping
            "H02": ("Pav Bhaji", 130.0, "hygiene"),
            "H03": ("Dahi Vada", 70.0, "hygiene"),
        }

        # Variables
        self.customer_name_var = StringVar()
        self.customer_phone_var = StringVar()
        self.bill_no_var = StringVar(value=str(self._new_bill_number()))
        self.search_bill_var = StringVar()
        self.selected_menu_code = StringVar()
        self.qty_var = StringVar(value="0")

        # Build UI
        self._build_ui()
        self._refresh_catalog_tree()

    def _new_bill_number(self):
        # random 6-digit number
        return random.randint(100000, 999999)

    def _build_ui(self):
        # Title
        title = Label(self.root, text="Restaurant Billing System (Upgraded)", font=("Arial", 18), bg="#2E86C1", fg="white")
        title.pack(fill=X)

        # Customer Frame
        cust_frame = LabelFrame(self.root, text="Customer Details", padx=10, pady=8)
        cust_frame.place(x=10, y=50, width=1180, height=70)

        Label(cust_frame, text="Name:").grid(row=0, column=0, sticky=W, padx=5)
        Entry(cust_frame, textvariable=self.customer_name_var, width=30).grid(row=0, column=1, padx=5)

        Label(cust_frame, text="Phone:").grid(row=0, column=2, sticky=W, padx=5)
        Entry(cust_frame, textvariable=self.customer_phone_var, width=20).grid(row=0, column=3, padx=5)

        Label(cust_frame, text="Bill No:").grid(row=0, column=4, sticky=W, padx=5)
        Entry(cust_frame, textvariable=self.bill_no_var, width=12, state='readonly').grid(row=0, column=5, padx=5)

        # Left: Catalog & Add Item
        left_frame = LabelFrame(self.root, text="Menu Catalog", padx=8, pady=8)
        left_frame.place(x=10, y=130, width=450, height=420)

        # Catalog Tree
        self.catalog_tree = ttk.Treeview(left_frame, columns=("code", "name", "price", "category"), show='headings', height=12)
        self.catalog_tree.heading("code", text="Code")
        self.catalog_tree.heading("name", text="Name")
        self.catalog_tree.heading("price", text="Price")
        self.catalog_tree.heading("category", text="Category")
        self.catalog_tree.column("code", width=60)
        self.catalog_tree.column("name", width=200)
        self.catalog_tree.column("price", width=70, anchor=E)
        self.catalog_tree.column("category", width=80)
        self.catalog_tree.pack(padx=5, pady=5, fill=BOTH, expand=True)
        self.catalog_tree.bind("<<TreeviewSelect>>", self._on_catalog_select)

        add_frame = Frame(left_frame)
        add_frame.pack(fill=X, padx=6, pady=6)
        Label(add_frame, text="Item Code:").grid(row=0, column=0, sticky=W)
        Entry(add_frame, textvariable=self.selected_menu_code, width=10).grid(row=0, column=1, padx=5)
        Label(add_frame, text="Qty:").grid(row=0, column=2, sticky=W)
        Entry(add_frame, textvariable=self.qty_var, width=8).grid(row=0, column=3, padx=5)
        Button(add_frame, text="Add to Bill", command=self.add_item_to_bill).grid(row=0, column=4, padx=6)

        # Middle: Bill Items & Controls
        mid_frame = LabelFrame(self.root, text="Current Bill", padx=8, pady=8)
        mid_frame.place(x=470, y=130, width=360, height=420)

        self.bill_items_tree = ttk.Treeview(mid_frame, columns=("name", "qty", "unit", "amount"), show='headings', height=14)
        self.bill_items_tree.heading("name", text="Name")
        self.bill_items_tree.heading("qty", text="Qty")
        self.bill_items_tree.heading("unit", text="Unit Price")
        self.bill_items_tree.heading("amount", text="Amount")
        self.bill_items_tree.column("name", width=140)
        self.bill_items_tree.column("qty", width=40, anchor=E)
        self.bill_items_tree.column("unit", width=80, anchor=E)
        self.bill_items_tree.column("amount", width=80, anchor=E)
        self.bill_items_tree.pack(fill=BOTH, expand=True, padx=5, pady=5)

        btns_frame = Frame(mid_frame)
        btns_frame.pack(fill=X, padx=4, pady=3)
        Button(btns_frame, text="Remove Selected", command=self.remove_selected_item).pack(side=LEFT, padx=4)
        Button(btns_frame, text="Clear Items", command=self.clear_items).pack(side=LEFT, padx=4)

        # Right: Bill Summary & Actions
        right_frame = LabelFrame(self.root, text="Summary & Actions", padx=8, pady=8)
        right_frame.place(x=840, y=130, width=350, height=420)

        Label(right_frame, text="Subtotal:").grid(row=0, column=0, sticky=W, padx=5, pady=4)
        self.subtotal_var = StringVar(value="0.00")
        Entry(right_frame, textvariable=self.subtotal_var, state='readonly', width=18).grid(row=0, column=1, padx=5)

        Label(right_frame, text="Tax:").grid(row=1, column=0, sticky=W, padx=5, pady=4)
        self.tax_var = StringVar(value="0.00")
        Entry(right_frame, textvariable=self.tax_var, state='readonly', width=18).grid(row=1, column=1, padx=5)

        Label(right_frame, text="Grand Total:").grid(row=2, column=0, sticky=W, padx=5, pady=4)
        self.total_var = StringVar(value="0.00")
        Entry(right_frame, textvariable=self.total_var, state='readonly', width=18).grid(row=2, column=1, padx=5)

        # Action Buttons
        Button(right_frame, text="Calculate Total", bg="#2ECC71", fg="white", command=self.calculate_total, width=20).grid(row=3, column=0, columnspan=2, pady=8)
        Button(right_frame, text="Save Bill", bg="#3498DB", fg="white", command=self.save_bill, width=20).grid(row=4, column=0, columnspan=2, pady=6)
        Button(right_frame, text="Export Invoice (PDF/TXT)", bg="#884EA0", fg="white", command=self.export_invoice, width=20).grid(row=5, column=0, columnspan=2, pady=6)
        Button(right_frame, text="New Bill", bg="#E67E22", fg="white", command=self.new_bill, width=20).grid(row=6, column=0, columnspan=2, pady=6)

        # Bottom: Search & History
        bottom_frame = LabelFrame(self.root, text="Search / History", padx=8, pady=8)
        bottom_frame.place(x=10, y=560, width=1180, height=130)

        Label(bottom_frame, text="Search Bill No:").grid(row=0, column=0, padx=6)
        Entry(bottom_frame, textvariable=self.search_bill_var, width=20).grid(row=0, column=1, padx=6)
        Button(bottom_frame, text="Search", command=self.search_bill).grid(row=0, column=2, padx=6)

        # Bill list
        self.history_tree = ttk.Treeview(bottom_frame, columns=("bill_no", "customer", "date", "total"), show='headings', height=4)
        self.history_tree.heading("bill_no", text="Bill No")
        self.history_tree.heading("customer", text="Customer")
        self.history_tree.heading("date", text="Date")
        self.history_tree.heading("total", text="Total")
        self.history_tree.column("bill_no", width=120)
        self.history_tree.column("customer", width=200)
        self.history_tree.column("date", width=300)
        self.history_tree.column("total", width=100, anchor=E)
        self.history_tree.grid(row=1, column=0, columnspan=6, pady=6, padx=6, sticky='nsew')

        Button(bottom_frame, text="Refresh History", command=self.refresh_history).grid(row=0, column=3, padx=6)

        # Initialize current bill structure
        self._init_new_bill_state()
        self.refresh_history()

    def _init_new_bill_state(self):
        # current bill object
        self.current_bill = Bill(str(self.bill_no_var.get()), Customer(self.customer_name_var.get(), self.customer_phone_var.get()))
        self._clear_bill_items_tree()

    # -------------------------
    # Catalog helpers
    # -------------------------
    def _refresh_catalog_tree(self):
        # Clear
        for r in self.catalog_tree.get_children():
            self.catalog_tree.delete(r)
        # Insert from catalog
        for code, (name, price, cat) in self.catalog.items():
            self.catalog_tree.insert("", END, values=(code, name, f"{price:.2f}", cat))

    def _on_catalog_select(self, event):
        sel = self.catalog_tree.selection()
        if not sel:
            return
        val = self.catalog_tree.item(sel[0], "values")
        code = val[0]
        self.selected_menu_code.set(code)
        self.qty_var.set("1")  # default to 1

    # -------------------------
    # Bill item management
    # -------------------------
    def add_item_to_bill(self):
        code = self.selected_menu_code.get().strip()
        qty_text = self.qty_var.get().strip()
        if not code:
            messagebox.showwarning("No Item Selected", "Please select or enter an item code first.")
            return
        if code not in self.catalog:
            messagebox.showerror("Invalid Code", f"Item code '{code}' not found in catalog.")
            return
        # validate qty
        try:
            qty = int(qty_text)
            if qty <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Invalid Quantity", "Quantity must be a positive integer.")
            return
        name, price, category = self.catalog[code]
        item = Item(code, name, price, qty)
        self.current_bill.add_item(category, item)
        self._insert_item_tree(item)
        self.calculate_total()

    def _insert_item_tree(self, item: Item):
        self.bill_items_tree.insert("", END, values=(item.name, item.qty, f"{item.unit_price:.2f}", f"{item.amount:.2f}"))

    def remove_selected_item(self):
        sel = self.bill_items_tree.selection()
        if not sel:
            messagebox.showinfo("Select item", "Please select an item in the bill to remove.")
            return
        # remove first selected row
        idx = self.bill_items_tree.index(sel[0])
        self.bill_items_tree.delete(sel[0])
        # remove from current_bill.items by index (careful: current_bill.items is list of (cat,item))
        try:
            del self.current_bill.items[idx]
            self.calculate_total()
        except Exception:
            # fallback: rebuild bill items from tree
            self._rebuild_bill_from_tree()

    def clear_items(self):
        if messagebox.askyesno("Clear Items", "Remove all items from the current bill?"):
            self._clear_bill_items_tree()
            self.current_bill.items.clear()
            self.calculate_total()

    def _clear_bill_items_tree(self):
        for r in self.bill_items_tree.get_children():
            self.bill_items_tree.delete(r)

    def _rebuild_bill_from_tree(self):
        # rebuild current_bill.items from the displayed tree (if needed)
        items = []
        for rowid in self.bill_items_tree.get_children():
            name, qty_s, unit_s, amount_s = self.bill_items_tree.item(rowid, "values")
            qty = int(qty_s)
            unit = float(unit_s)
            # find code & category from catalog by name+unit
            found = None
            for code, (nm, pr, cat) in self.catalog.items():
                if nm == name and float(pr) == unit:
                    found = (code, nm, pr, cat)
                    break
            if found:
                code, nm, pr, cat = found
                item = Item(code, nm, pr, qty)
                items.append((cat, item))
            else:
                # generic
                item = Item("", name, unit, qty)
                items.append(("other", item))
        self.current_bill.items = items

    # -------------------------
    # Calculation / Save / Export
    # -------------------------
    def calculate_total(self):
        # ensure the current_bill has customer info synced
        self.current_bill.customer.name = self.customer_name_var.get().strip()
        self.current_bill.customer.phone = self.customer_phone_var.get().strip()
        # if items in tree but not in current_bill (like after restart), rebuild
        self._rebuild_bill_from_tree()
        subtotal = self.current_bill.subtotal
        tax = self.current_bill.total_tax
        total = self.current_bill.grand_total
        self.subtotal_var.set(f"{subtotal:.2f}")
        self.tax_var.set(f"{tax:.2f}")
        self.total_var.set(f"{total:.2f}")
        return subtotal, tax, total

    def save_bill(self):
        # Validation
        if not self.customer_name_var.get().strip():
            messagebox.showerror("Validation Error", "Customer name cannot be empty.")
            return
        if not self.customer_phone_var.get().strip():
            messagebox.showerror("Validation Error", "Customer phone number cannot be empty.")
            return
        if not any(item.qty > 0 for _, item in self.current_bill.items):
            messagebox.showerror("Validation Error", "No items in the bill.")
            return

        # Update bill header info
        self.current_bill.bill_no = str(self.bill_no_var.get())
        self.current_bill.customer = Customer(self.customer_name_var.get(), self.customer_phone_var.get())
        self.current_bill.date = datetime.now().isoformat(timespec='seconds')
        self.calculate_total()

        # Save to DB
        try:
            self.db.save_bill(self.current_bill)
            messagebox.showinfo("Saved", f"Bill {self.current_bill.bill_no} saved successfully.")
            self.refresh_history()
        except sqlite3.IntegrityError:
            messagebox.showerror("Save Error", "A bill with this number already exists. Please click 'New Bill' to create a new bill number.")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save bill: {e}")

    def export_invoice(self):
        # Create bill record using current data
        if not any(item.qty > 0 for _, item in self.current_bill.items):
            messagebox.showerror("No Items", "Add items to the bill before exporting the invoice.")
            return
        self.current_bill.customer = Customer(self.customer_name_var.get(), self.customer_phone_var.get())
        self.calculate_total()

        # Ask where to save
        filetypes = [("PDF File", "*.pdf")] if FPDF_AVAILABLE else [("Text File", "*.txt"), ("All Files", "*.*")]
        initialname = f"invoice_{self.current_bill.bill_no}"
        if FPDF_AVAILABLE:
            filepath = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=filetypes, initialfile=initialname)
        else:
            filepath = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=filetypes, initialfile=initialname)

        if not filepath:
            return

        try:
            if FPDF_AVAILABLE and filepath.lower().endswith(".pdf"):
                self._generate_pdf_invoice(filepath, self.current_bill)
            else:
                self._generate_text_invoice(filepath, self.current_bill)
            messagebox.showinfo("Exported", f"Invoice exported: {filepath}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export invoice: {e}")

    def _generate_text_invoice(self, path, bill: Bill):
        lines = []
        lines.append("---- RESTAURANT INVOICE ----")
        lines.append(f"Bill No: {bill.bill_no}")
        lines.append(f"Date: {bill.date}")
        lines.append(f"Customer: {bill.customer.name}")
        lines.append(f"Phone: {bill.customer.phone}")
        lines.append("-" * 40)
        lines.append(f"{'Item':25s}{'Qty':>4s}{'Price':>9s}{'Amt':>9s}")
        lines.append("-" * 40)
        for cat, item in bill.items:
            lines.append(f"{item.name[:25]:25s}{item.qty:4d}{item.unit_price:9.2f}{item.amount:9.2f}")
        lines.append("-" * 40)
        lines.append(f"Subtotal: {bill.subtotal:.2f}")
        taxes = bill.taxes_by_category()
        for cat, val in taxes.items():
            lines.append(f"Tax ({cat}): {val:.2f}")
        lines.append(f"Total Tax: {bill.total_tax:.2f}")
        lines.append(f"Grand Total: {bill.grand_total:.2f}")
        lines.append("-" * 40)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _generate_pdf_invoice(self, path, bill: Bill):
        # using fpdf2
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("Arial", "B", 16)
        pdf.cell(0, 10, "RESTAURANT INVOICE", ln=True, align="C")
        pdf.set_font("Arial", size=10)
        pdf.ln(4)
        pdf.cell(100, 6, f"Bill No: {bill.bill_no}")
        pdf.cell(0, 6, f"Date: {bill.date}", ln=True)
        pdf.cell(0, 6, f"Customer: {bill.customer.name}    Phone: {bill.customer.phone}", ln=True)
        pdf.ln(4)
        # header
        pdf.set_font("Arial", "B", 10)
        pdf.cell(90, 6, "Item", border=1)
        pdf.cell(20, 6, "Qty", border=1, align='R')
        pdf.cell(30, 6, "Unit", border=1, align='R')
        pdf.cell(30, 6, "Amount", border=1, align='R', ln=True)
        pdf.set_font("Arial", size=10)
        for cat, item in bill.items:
            pdf.cell(90, 6, item.name[:40], border=1)
            pdf.cell(20, 6, str(item.qty), border=1, align='R')
            pdf.cell(30, 6, f"{item.unit_price:.2f}", border=1, align='R')
            pdf.cell(30, 6, f"{item.amount:.2f}", border=1, align='R', ln=True)
        pdf.ln(2)
        pdf.cell(0, 6, f"Subtotal: {bill.subtotal:.2f}", ln=True, align='R')
        taxes = bill.taxes_by_category()
        for cat, val in taxes.items():
            pdf.cell(0, 6, f"Tax ({cat}): {val:.2f}", ln=True, align='R')
        pdf.cell(0, 6, f"Total Tax: {bill.total_tax:.2f}", ln=True, align='R')
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, f"Grand Total: {bill.grand_total:.2f}", ln=True, align='R')
        pdf.output(path)

    # -------------------------
    # Bill lifecycle helpers
    # -------------------------
    def new_bill(self):
        if messagebox.askyesno("New Bill", "Start a new bill? Current unsaved items will be cleared."):
            self.customer_name_var.set("")
            self.customer_phone_var.set("")
            newno = str(self._new_bill_number())
            self.bill_no_var.set(newno)
            self.current_bill = Bill(newno, Customer("", ""))
            self._clear_bill_items_tree()
            self.subtotal_var.set("0.00")
            self.tax_var.set("0.00")
            self.total_var.set("0.00")

    def search_bill(self):
        bno = self.search_bill_var.get().strip()
        if not bno:
            messagebox.showwarning("Input needed", "Enter a bill number to search.")
            return
        rec = self.db.get_bill(bno)
        if not rec:
            messagebox.showinfo("Not found", f"No bill found for bill number: {bno}")
            return
        bill = Bill.from_record(rec)
        # populate GUI with bill details (read-only state for current session)
        self.bill_no_var.set(bill.bill_no)
        self.customer_name_var.set(bill.customer.name)
        self.customer_phone_var.set(bill.customer.phone)
        # show items
        self._clear_bill_items_tree()
        for cat, item in bill.items:
            self._insert_item_tree(item)
        # set current_bill from record
        self.current_bill = bill
        self.calculate_total()

    def refresh_history(self):
        # clear
        for r in self.history_tree.get_children():
            self.history_tree.delete(r)
        records = self.db.list_bills(limit=50)
        for r in records:
            self.history_tree.insert("", END, values=(r["bill_no"], r["customer_name"], r["date"], f"{r['total']:.2f}"))

    def on_close(self):
        # cleanup
        try:
            self.db.close()
        except Exception:
            pass
        self.root.destroy()


# ----------------------------
# Run application
# ----------------------------
if __name__ == "__main__":
    root = Tk()
    app = BillApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
