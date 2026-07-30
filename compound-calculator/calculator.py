"""
Standalone Compound Calculator
Run on computer:  python calculator.py
No browser. No other project. Just this app.
"""

from __future__ import annotations

import flet as ft


def compound_schedule(
    principal: float,
    daily_rate_pct: float,
    monthly_rate_pct: float,
    months: int,
) -> tuple[float, list[tuple[int, int, str, float]]]:
    """Return final balance and every-day rows: (day, month, what, balance)."""
    daily_factor = 1 + daily_rate_pct / 100
    monthly_factor = 1 + monthly_rate_pct / 100
    balance = principal
    rows: list[tuple[int, int, str, float]] = [(0, 0, "Start", balance)]
    day = 0

    for month in range(1, months + 1):
        for d in range(1, 31):
            day += 1
            balance *= daily_factor
            what = f"Daily ×{daily_factor:.4f}"
            if d == 30 and monthly_rate_pct > 0:
                balance *= monthly_factor
                what += f" + Monthly ×{monthly_factor:.4f}"
            rows.append((day, month, what, balance))

    return balance, rows


def money(n: float) -> str:
    return f"${n:,.2f}"


def main(page: ft.Page) -> None:
    page.title = "Compound Calculator"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO
    page.window.width = 520
    page.window.height = 780

    principal = ft.TextField(label="Principal", value="100", keyboard_type=ft.KeyboardType.NUMBER)
    daily_rate = ft.TextField(label="Daily rate (%)", value="15", keyboard_type=ft.KeyboardType.NUMBER)
    monthly_rate = ft.TextField(label="Monthly rate (%)", value="3", keyboard_type=ft.KeyboardType.NUMBER)
    months = ft.TextField(label="Number of months", value="2", keyboard_type=ft.KeyboardType.NUMBER)

    final_text = ft.Text("Final balance: —", size=22, weight=ft.FontWeight.BOLD)
    interest_text = ft.Text("Interest earned: —", size=16)
    days_text = ft.Text("Days: —", size=14)

    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Day")),
            ft.DataColumn(ft.Text("Month")),
            ft.DataColumn(ft.Text("What happened")),
            ft.DataColumn(ft.Text("Balance")),
        ],
        rows=[],
        column_spacing=12,
    )
    table_host = ft.Column([table], scroll=ft.ScrollMode.AUTO, height=360)

    error_text = ft.Text("", color=ft.Colors.RED_700)

    def calculate(_: ft.ControlEvent | None = None) -> None:
        error_text.value = ""
        try:
            p = max(0.0, float(principal.value or 0))
            dr = max(0.0, float(daily_rate.value or 0))
            mr = max(0.0, float(monthly_rate.value or 0))
            m = max(0, int(float(months.value or 0)))
        except ValueError:
            error_text.value = "Enter valid numbers."
            page.update()
            return

        final, rows = compound_schedule(p, dr, mr, m)
        final_text.value = f"Final balance: {money(final)}"
        interest_text.value = f"Interest earned: {money(final - p)}"
        days_text.value = f"Days used: {m * 30}  |  Months applied: {m}"

        table.rows = [
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(day))),
                    ft.DataCell(ft.Text("-" if month == 0 else str(month))),
                    ft.DataCell(ft.Text(what)),
                    ft.DataCell(ft.Text(money(bal))),
                ]
            )
            for day, month, what, bal in rows
        ]
        page.update()

    page.add(
        ft.Text("Compound Calculator", size=28, weight=ft.FontWeight.BOLD),
        ft.Text("Standalone app — not part of any other project.", size=13),
        ft.Divider(),
        principal,
        daily_rate,
        monthly_rate,
        months,
        ft.ElevatedButton("Calculate", on_click=calculate, width=200),
        error_text,
        ft.Divider(),
        final_text,
        interest_text,
        days_text,
        ft.Text("Every-day breakdown", size=16, weight=ft.FontWeight.W_600),
        table_host,
    )

    calculate()


if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.FLET_APP)
