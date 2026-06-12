using System;

namespace NavisworksBridge
{
    [AttributeUsage(AttributeTargets.Method, Inherited = false, AllowMultiple = false)]
    public sealed class BridgeCommandAttribute : Attribute
    {
        public string Name { get; }
        public bool IsMutating { get; set; }
        public bool ConfirmationRequired { get; set; }

        public BridgeCommandAttribute(string name)
        {
            Name = name;
            IsMutating = true;
            ConfirmationRequired = false;
        }
    }
}
