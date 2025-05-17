/** @odoo-module **/

import { registry } from "@web/core/registry";
import { usePopover } from "@web/core/popover/popover_hook";
import { useService } from "@web/core/utils/hooks";
import { localization } from "@web/core/l10n/localization";
import { parseDate, formatDate } from "@web/core/l10n/dates";

import { formatMonetary } from "@web/views/fields/formatters";

import { patch } from "@web/core/utils/patch";0
import { AccountPaymentField } from "@account/components/account_payment_field/account_payment_field";

const { Component, onWillUpdateProps } = owl;

patch(AccountPaymentField.prototype, 'sr_partial_invoice_payment', {
    async assignOutstandingCredit(id) {
        var move_type = await this.orm.call(this.props.record.resModel, 'js_check_move_type', [this.move_id], {});
        if (move_type == "out_invoice"){
            var actionPerform = this.action.doAction({
                name: _('Partial Payment'),
                res_model: 'partial.payment.wizard',
                view_mode: 'form',
                views: [[false, 'form']],
                context: {
                    'active_model': 'account.move',
                    'active_id': this.move_id,
                    'line_id':id,
                    'remaining_credit': this.lines[0].amount
                },
                target: 'new',
                type: 'ir.actions.act_window',
            });
        } else {
            await this.orm.call(this.props.record.resModel, 'js_assign_outstanding_line', [this.move_id, id], {});
            await this.props.record.model.root.load();
            this.props.record.model.notify();
        }
    }
});

