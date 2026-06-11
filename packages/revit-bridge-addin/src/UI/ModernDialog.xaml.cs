using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using RevitBridge;

namespace RevitBridge.UI
{
    public partial class ModernDialog : Window
    {
        private readonly Brush _bgBrush;
        private readonly Brush _cardBgBrush;
        private readonly Brush _textPrimaryBrush;
        private readonly Brush _textSecondaryBrush;
        private readonly Brush _borderBrush;
        private readonly Brush _headerBrush;
        private readonly Brush _footerBgBrush;
        private readonly Brush _footerBorderBrush;

        public ModernDialog()
        {
            // Detect Revit Theme
            bool isDark = false;
            try
            {
                isDark = Autodesk.Revit.UI.UIThemeManager.CurrentTheme == Autodesk.Revit.UI.UITheme.Dark;
            }
            catch
            {
                // Fallback if UIThemeManager is not available
            }

            // Establish professional, Revit-aligned color system
            if (isDark)
            {
                _bgBrush = new SolidColorBrush(Color.FromRgb(43, 43, 43)); // Dark charcoal
                _cardBgBrush = new SolidColorBrush(Color.FromRgb(51, 51, 51)); // Medium charcoal
                _textPrimaryBrush = new SolidColorBrush(Color.FromRgb(224, 224, 224)); // Soft white
                _textSecondaryBrush = new SolidColorBrush(Color.FromRgb(170, 170, 170)); // Slate gray
                _borderBrush = new SolidColorBrush(Color.FromRgb(68, 68, 68)); // Charcoal border
                _headerBrush = new SolidColorBrush(Color.FromRgb(31, 31, 31)); // Rich near-black header
                _footerBgBrush = new SolidColorBrush(Color.FromRgb(37, 37, 37)); // Footer background
                _footerBorderBrush = new SolidColorBrush(Color.FromRgb(48, 48, 48)); // Footer border
            }
            else
            {
                _bgBrush = new SolidColorBrush(Color.FromRgb(240, 240, 240)); // Professional light gray
                _cardBgBrush = new SolidColorBrush(Color.FromRgb(255, 255, 255)); // Flawless white
                _textPrimaryBrush = new SolidColorBrush(Color.FromRgb(34, 34, 34)); // Dark charcoal text
                _textSecondaryBrush = new SolidColorBrush(Color.FromRgb(85, 85, 85)); // Muted slate text
                _borderBrush = new SolidColorBrush(Color.FromRgb(208, 208, 208)); // Professional border gray
                _headerBrush = new SolidColorBrush(Color.FromRgb(29, 58, 86)); // Sleek corporate Revit Blue/Slate
                _footerBgBrush = new SolidColorBrush(Color.FromRgb(245, 245, 245)); // Off-white footer
                _footerBorderBrush = new SolidColorBrush(Color.FromRgb(224, 224, 224)); // Footer separator
            }

            // Expose as DynamicResources before initializing components so XAML bindings compile and evaluate perfectly
            Resources["BgBrush"] = _bgBrush;
            Resources["CardBgBrush"] = _cardBgBrush;
            Resources["TextPrimaryBrush"] = _textPrimaryBrush;
            Resources["TextSecondaryBrush"] = _textSecondaryBrush;
            Resources["BorderBrush"] = _borderBrush;
            Resources["HeaderBrush"] = _headerBrush;
            Resources["FooterBgBrush"] = _footerBgBrush;
            Resources["FooterBorderBrush"] = _footerBorderBrush;

            InitializeComponent();

            // Enable dragging by clicking anywhere on the header
            MouseDown += (s, e) =>
            {
                if (e.ChangedButton == MouseButton.Left && e.GetPosition(this).Y < 68)
                {
                    DragMove();
                }
            };

            KeyDown += (s, e) =>
            {
                if (e.Key == Key.Escape)
                {
                    Close();
                }
            };
        }

        public void SetTitle(string title, string subtitle = "")
        {
            DialogTitle.Text = title;
            DialogSubtitle.Text = subtitle;
            if (string.IsNullOrEmpty(subtitle))
            {
                DialogSubtitle.Visibility = Visibility.Collapsed;
            }
        }

        public void AddStatusCard(string icon, string label, string value, Brush? iconColor = null)
        {
            var card = new Border
            {
                Style = (Style)FindResource("StatCard"),
                MinHeight = 60
            };

            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(50) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            // Icon
            var iconText = new TextBlock
            {
                Text = icon,
                FontSize = 32,
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center,
                Foreground = iconColor ?? new SolidColorBrush(Color.FromRgb(33, 150, 243)) // Blue
            };
            Grid.SetColumn(iconText, 0);
            grid.Children.Add(iconText);

            // Text Stack
            var textStack = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(10, 0, 0, 0)
            };

            var labelText = new TextBlock
            {
                Text = label,
                FontSize = 12,
                Foreground = (Brush)FindResource("TextSecondaryBrush"),
                Margin = new Thickness(0, 0, 0, 5)
            };

            var valueText = new TextBlock
            {
                Text = value,
                FontSize = 18,
                FontWeight = FontWeights.SemiBold,
                Foreground = (Brush)FindResource("TextPrimaryBrush")
            };

            textStack.Children.Add(labelText);
            textStack.Children.Add(valueText);
            Grid.SetColumn(textStack, 1);
            grid.Children.Add(textStack);

            card.Child = grid;
            ContentPanel.Children.Add(card);
        }

        public void AddInfoSection(string title, string content)
        {
            var section = new StackPanel { Margin = new Thickness(0, 10, 0, 10) };

            var titleText = new TextBlock
            {
                Text = title,
                FontSize = 14,
                FontWeight = FontWeights.SemiBold,
                Foreground = (Brush)FindResource("TextPrimaryBrush"),
                Margin = new Thickness(0, 0, 0, 8)
            };

            var contentBorder = new Border
            {
                Background = (Brush)FindResource("BgBrush"),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(14),
                BorderBrush = (Brush)FindResource("BorderBrush"),
                BorderThickness = new Thickness(1)
            };

            var contentText = new TextBlock
            {
                Text = content,
                FontSize = 12,
                Foreground = (Brush)FindResource("TextSecondaryBrush"),
                TextWrapping = TextWrapping.Wrap,
                FontFamily = new FontFamily("Consolas")
            };

            contentBorder.Child = contentText;
            section.Children.Add(titleText);
            section.Children.Add(contentBorder);
            ContentPanel.Children.Add(section);
        }

        public void AddStatsGrid(params (string icon, string label, string value)[] stats)
        {
            var grid = new Grid { Margin = new Thickness(0, 10, 0, 0) };

            int columns = Math.Min(stats.Length, 3);
            for (int i = 0; i < columns; i++)
            {
                grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            }

            for (int i = 0; i < stats.Length; i++)
            {
                var stat = stats[i];
                var card = CreateStatCard(stat.icon, stat.label, stat.value);
                Grid.SetColumn(card, i % columns);
                Grid.SetRow(card, i / columns);

                if (i / columns >= grid.RowDefinitions.Count)
                {
                    grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                }

                grid.Children.Add(card);
            }

            ContentPanel.Children.Add(grid);
        }

        private Border CreateStatCard(string icon, string label, string value)
        {
            var card = new Border
            {
                Style = (Style)FindResource("StatCard")
            };

            var stack = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center };

            var iconText = new TextBlock
            {
                Text = icon,
                FontSize = 28,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 8)
            };

            var valueText = new TextBlock
            {
                Text = value,
                FontSize = 20,
                FontWeight = FontWeights.Bold,
                HorizontalAlignment = HorizontalAlignment.Center,
                Foreground = new SolidColorBrush(Color.FromRgb(33, 150, 243)), // Autodesk Blue
                Margin = new Thickness(0, 0, 0, 4)
            };

            var labelText = new TextBlock
            {
                Text = label,
                FontSize = 11,
                HorizontalAlignment = HorizontalAlignment.Center,
                Foreground = (Brush)FindResource("TextSecondaryBrush")
            };

            stack.Children.Add(iconText);
            stack.Children.Add(valueText);
            stack.Children.Add(labelText);

            card.Child = stack;
            return card;
        }

        public void AddSeparator()
        {
            var separator = new Border
            {
                Height = 1,
                Background = (Brush)FindResource("BorderBrush"),
                Margin = new Thickness(0, 15, 0, 15)
            };
            ContentPanel.Children.Add(separator);
        }

        public void AddLinkButtons(params (string label, string url)[] links)
        {
            var panel = new WrapPanel
            {
                Margin = new Thickness(0, 8, 0, 8),
                HorizontalAlignment = HorizontalAlignment.Left
            };

            foreach (var link in links)
            {
                var button = new Button
                {
                    Content = link.label,
                    Style = (Style)FindResource("SecondaryButton"),
                    Padding = new Thickness(14, 7, 14, 7),
                    Margin = new Thickness(0, 0, 8, 8),
                    ToolTip = link.url
                };
                button.Click += (s, e) =>
                {
                    if (!ProductInfo.TryOpenUrl(link.url, out var error))
                    {
                        MessageBox.Show(
                            this,
                            $"Could not open the link.\n\n{link.url}\n\n{error}",
                            ProductInfo.ProductName,
                            MessageBoxButton.OK,
                            MessageBoxImage.Warning
                        );
                    }
                };
                panel.Children.Add(button);
            }

            ContentPanel.Children.Add(panel);
        }

        public void SetActionButton(string text, Action? action = null)
        {
            ActionButton.Content = text;
            if (action != null)
            {
                ActionButton.Click += (s, e) =>
                {
                    action();
                    Close();
                };
            }
        }

        public void ShowCancelButton(Action? action = null)
        {
            CancelButton.Visibility = Visibility.Visible;
            if (action != null)
            {
                CancelButton.Click += (s, e) =>
                {
                    action();
                    Close();
                };
            }
        }

        private void CloseButton_Click(object sender, RoutedEventArgs e)
        {
            Close();
        }

        private void ActionButton_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = true;
            Close();
        }

        private void CancelButton_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }
    }
}
