# AI Refactoring Prompt: Platform-Native Dialog Button Ordering

Use the prompt below with your AI coding assistant (Cursor, GitHub Copilot, Claude, etc.) alongside the UI/dialog files you have modified. It ensures buttons automatically adapt between Windows (`OK / Cancel`) and Linux/GTK (`Cancel / OK`, respecting `gtk-alternative-button-order`).

---

## Copy-Paste Prompt

```markdown
Review the attached UI/dialog files and refactor all dialog action button layouts so they automatically adapt to platform-native button ordering (Windows `OK / Cancel` vs. Linux/GTK `Cancel / OK`, respecting `gtk-alternative-button-order`).

**Follow these exact rules:**
1. Replace any standard `wxBoxSizer` used for dialog buttons with `wxStdDialogButtonSizer`.
2. Ensure all buttons passed into `wxStdDialogButtonSizer` use standard wxWidgets stock IDs (`wxID_OK`, `wxID_CANCEL`, `wxID_YES`, `wxID_NO`, `wxID_APPLY`, `wxID_HELP`) and are added via `AddButton()`. If custom button labels are needed, set the label on the `wxButton` object while keeping the stock ID.
3. Ensure `sizer->Realize()` is called after all buttons are added.
4. Remove any manual `AddSpacer()` calls between those buttons, as `Realize()` handles platform-specific padding.
5. Do not hardcode `gtk-alternative-button-order` in the C++ source; let the native GTK3/Windows environment dictate the order through `wxStdDialogButtonSizer`.
```

---

## Reference Pattern (Before vs. After)

### Wrong (Locked Order)
```cpp
wxBoxSizer* btnSizer = new wxBoxSizer(wxHORIZONTAL);
btnSizer->Add(new wxButton(this, wxID_OK, "Save"), 0, wxALL, 5);
btnSizer->Add(new wxButton(this, wxID_CANCEL, "Cancel"), 0, wxALL, 5);
```

### Right (Platform-Adaptive Order)
```cpp
wxStdDialogButtonSizer* btnSizer = new wxStdDialogButtonSizer();
btnSizer->AddButton(new wxButton(this, wxID_OK, "Save"));
btnSizer->AddButton(new wxButton(this, wxID_CANCEL, "Cancel"));
btnSizer->Realize(); // Triggers automatic Windows/Linux sorting
mainSizer->Add(btnSizer, 0, wxEXPAND | wxALL, 10);
```
