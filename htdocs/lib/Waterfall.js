function WaterfallButton() {
    var $waterfallButton = $('#openwebrx-panel-receiver').find('.openwebrx-waterfall-button');
    $waterfallButton.show();
    $waterfallButton.click(toggleWaterfall);

}
