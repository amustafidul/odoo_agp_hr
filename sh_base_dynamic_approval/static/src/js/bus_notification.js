odoo.define('sh_base_dynamic_approval.NotificationManager', function (require) {
    "use strict";
    var AbstractService = require('web.AbstractService');
    var core = require("web.core");
    var SHNotificationManager = AbstractService.extend({

        /**
     * @override
     */
    start: function () {
        this._super.apply(this, arguments);
        core.bus.on('web_client_ready', null, () => {
            this.call('bus_service', 'addEventListener', 'notification', this._onNotification.bind(this));
        });
    },

    _onNotification: function({ detail: notifications }) {
        for (const { payload, type } of notifications) {
            if (type === "sh_notification_info") {
                this.displayNotification({ title: payload.title, message: payload.message, type: 'info',sticky : true });
            }
            if (type === "sh_notification_alert") {
                this.displayNotification({ title: payload.title, message: payload.message, type: 'danger',sticky : true });
            }
        }
    }
    
    });

    core.serviceRegistry.add('sh_notification_service', SHNotificationManager);

    return SHNotificationManager;

});